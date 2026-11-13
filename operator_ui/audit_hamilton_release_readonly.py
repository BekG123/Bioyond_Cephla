"""Read-only firmware/drive audit for DCG inward-motion investigation.

Allows only introspection and explicitly named status methods with no inputs.
Never calls setup, initialization, MethodBegin, abort, or any motion/settings command.
"""
import asyncio
from datetime import datetime, timezone
import json
import time
from pathlib import Path
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, to_jsonable

ROOT = Path(__file__).resolve().parent
NAMES = {'GetPosition', 'GetPositions', 'GetStatus', 'Adjustments', 'GetCurrent',
         'GetTravelLimitsEnable', 'GetInitializationDistance', 'GetHomeFlagLength',
         'GetHomeFlagPosition', 'GetLastSlewDrive', 'GetDriveOutput', 'GetDriveAngle',
         'GetPhaseOffset', 'GetCurrentDestination', 'GetPlateHeld', 'GetTipDefinitionHeld',
         'GetIsInitialized', 'IsParked', 'GetXSpeedScale', 'GetZSpeedScale',
         'GetSafeSpeedsEnabled', 'GetDefaultTraverseHeight', 'GetChannelBounds',
         'FirmwareVersion', 'BootLoaderVersion', 'SerialNumber', 'GetTraceVariables',
         'GetTraceVariableCount', 'GetReportRate', 'GetReporter', 'GetFirmwareVersion',
         'GetModuleVersion', 'GetHardwareRevision', 'GetSerialNumber'}

async def audit():
    permitted = set()
    class Reader(PrepDriver):
        async def setup(self, **kw): raise RuntimeError('Read-only audit')
        async def stop(self, **kw): raise RuntimeError('Read-only audit; transport close only')
        async def send_command(self, cmd, **kw):
            if type(cmd) is not C.PrepProbeRequest or (cmd.dest,cmd.interface_id,cmd.command_id) not in permitted:
                raise RuntimeError('Only metadata-verified, allowlisted status requests permitted')
            return await super().send_command(cmd, **kw)
    d = Reader(deck=Deck(name='readonly_release_audit',size_x=300,size_y=430,size_z=200),
               io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=5,write_timeout=5))
    out = dict(motion_sent=False, settings_changed=False, time_utc=datetime.now(timezone.utc).isoformat(), objects={})
    try:
        await asyncio.wait_for(d._open(), 20)
        paths = ['MLPrepRoot.MLPrep','MLPrepRoot.MLPrepCpu','MLPrepRoot.ChannelCoordinator.ChannelXYZCoordinator',
                 'MLPrepRoot.PipettorRoot.Pipettor','MLPrepRoot.HamTrace']
        addresses = [(p,await d.resolve_path(p)) for p in paths]
        drives = await d.request_channel_drives(root_name='Ngc')
        root=await d.resolve_path('MLPrepRoot')
        info=await d.io.introspection.get_object(root)
        for index in range(info.subobject_count):
            child=await d.io.introspection.get_subobject_address(root,index)
            child_info=await d.io.introspection.get_object(child)
            if child_info.name!='Ngc': continue
            for index2 in range(child_info.subobject_count):
                part=await d.io.introspection.get_subobject_address(child,index2)
                part_info=await d.io.introspection.get_object(part)
                if part_info.name in ('CPU','HeadCPU'):
                    addresses.append((part_info.name+'/'+str(part),part))
        out['global_objects']={}
        for addr in d.io.global_object_addresses:
            out['global_objects'][str(addr)]=dict(info=to_jsonable(await d.io.introspection.get_object(addr)),
                structs=to_jsonable(await d.io.introspection.get_structs(addr,1)),
                enums=to_jsonable(await d.io.introspection.get_enums(addr,1)))
        for kind in ('yaxis_addrs','ydrive_addrs'):
            addresses.extend((kind+'/'+str(a),a) for a in getattr(drives,kind))
        for label,addr in addresses:
            info = await d.io.introspection.get_object(addr)
            table = await d.io.introspection.ensure_method_table(addr)
            obj = dict(address=to_jsonable(addr),info=to_jsonable(info),methods=[],reads={})
            out['objects'][label]=obj
            for method in table:
                obj['methods'].append(dict(**method.to_dict(),call_type=method.call_type,
                                           parameter_types=to_jsonable(method.parameter_types),
                                           return_types=to_jsonable(method.return_types)))
                if method.name not in NAMES or method.call_type != 0 or method.parameter_types: continue
                permitted.add((addr,method.interface_id,method.method_id))
                try:
                    data=await d.send_command(C.PrepProbeRequest(dest=addr,interface_id=method.interface_id,command_id=method.method_id))
                    obj['reads'][method.name]=dict(hex=data.hex(),values=to_jsonable(C.HoiParamsParser(data).parse_all()))
                except Exception as error:
                    obj['reads'][method.name]=dict(error=str(error))
            for iid in sorted({m.interface_id for m in table if m.interface_id}):
                try:
                    obj.setdefault('types',{})[iid]=dict(structs=to_jsonable(await d.io.introspection.get_structs(addr,iid)),
                                                       enums=to_jsonable(await d.io.introspection.get_enums(addr,iid)))
                except Exception as error: obj.setdefault('type_errors',{})[iid]=str(error)
            obj['fault_descriptions']={hex(code):await d.io.introspection.get_hc_result_text(addr,1,code)
                                       for code in (0x0f03,0x0f09)}
        out['stationary_drive_samples']=[]
        for _ in range(10):
            sample=dict(at=time.time(),drives={})
            for addr in drives.ydrive_addrs:
                method=await d.request_method_by_name(addr,'GetStatus')
                data=await d.send_command(C.PrepProbeRequest(dest=addr,interface_id=method.interface_id,command_id=method.method_id))
                outer=C.HoiParamsParser(data).parse_all()
                sample['drives'][str(addr)]=dict(hex=data.hex(),fields=to_jsonable(C.HoiParamsParser(outer[0][1]).parse_all()))
            out['stationary_drive_samples'].append(sample)
            await asyncio.sleep(.2)
        return out
    finally: await d._close()

if __name__=='__main__':
    folder=ROOT/'reports/hamilton_api/release_investigation_20261109'
    folder.mkdir(exist_ok=True)
    h=HamiltonPrep()
    rest={}
    for endpoint in ('instruments/connection-info','instruments/global-run-state',
                     'errors/check-for-pending-errors','traces?offset=0&limit=1000&sources=MNE,RTE,SDE'):
        try: rest[endpoint]=h.call('GET',endpoint)
        except Exception as error: rest[endpoint]=dict(error=str(error))
    data=asyncio.run(audit())
    data['rest']=rest
    path=folder/'readonly_firmware_audit_final.json'
    encode=lambda v: {'raw_bytes_hex':v.hex()} if isinstance(v,bytes) else str(v)
    path.write_text(json.dumps(data,indent=2,default=encode),encoding='utf-8')
    print(path)
    for label,obj in data['objects'].items():
        if 'CPU' in label or 'Cpu' in label: print(label,json.dumps(obj['reads'],default=encode))
    print('Global type objects:',list(data['global_objects']))
    print('Stationary samples:',len(data['stationary_drive_samples']))
