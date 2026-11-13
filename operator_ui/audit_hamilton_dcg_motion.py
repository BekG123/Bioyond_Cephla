"""Read-only firmware motion signatures and current empty-test state."""
import asyncio
import json
from datetime import datetime, timezone
from hamilton_dcg_transfer import C, PrepDriver, HamiltonTCPClient, Deck, HamiltonPrep, to_jsonable

async def audit():
    allowed={C.PrepGetPositions,C.PrepGetChannelBounds,C.PrepGetPlateHeld,C.PrepGetIsInitialized,C.PrepGetTipDefinitionHeld}
    class ReadOnly(PrepDriver):
        async def send_command(self,command,**kwargs):
            if type(command) not in allowed:raise RuntimeError('Read-only audit')
            return await super().send_command(command,**kwargs)
        async def setup(self,**kw):raise RuntimeError('No setup')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
    d=ReadOnly(deck=Deck(name='audit',size_x=300,size_y=430,size_z=200),io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=8,write_timeout=5))
    result={'motion_sent':False}
    try:
        await d._open()
        result['state']={cls.__name__:to_jsonable(await d.send_command(cls())) for cls in allowed}
        result['methods']={}
        result['local_types']={}
        pool=await d.io.introspection.ensure_global_type_pool()
        for path in ('MLPrepRoot.MLPrep','MLPrepRoot.ChannelCoordinator.ChannelXYZCoordinator','MLPrepRoot.PipettorRoot.Pipettor'):
            table=await d.io.introspection.ensure_method_table(path)
            result['methods'][path]=[m.to_dict() for m in table if path.endswith('ChannelXYZCoordinator') or any(s in m.name.lower() for s in ('pause','method','speed','velocity','movey','movez','movetoposition','plate','error'))]
            addr=await d.resolve_path(path)
            if path.endswith('ChannelXYZCoordinator'):
                result['local_types'][path]=to_jsonable(await d.io.introspection.get_structs(addr,1))
        result['global_types']=pool.to_dict()
        return result
    finally:await d._close()

if __name__=='__main__':
    h=HamiltonPrep()
    if h.status(fresh=True).get('serial')!='PRPGJ2494':raise RuntimeError('Wrong instrument')
    out=h.folder/('dcg_motion_audit_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    out.write_text('{}')
    data=asyncio.run(audit());out.write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(out)
    print(json.dumps(data['methods']['MLPrepRoot.ChannelCoordinator.ChannelXYZCoordinator'],indent=2))
