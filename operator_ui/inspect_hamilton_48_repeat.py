"""Read-only stopped-state snapshot. No reset, setup or motion commands."""
import asyncio
import json
from hamilton_dcg_transfer import C,PrepDriver,HamiltonTCPClient,Deck,HamiltonPrep,to_jsonable

async def snapshot():
    allowed={C.PrepGetPositions,C.PrepGetPlateHeld,C.PrepGetTipDefinitionHeld,C.PrepGetIsInitialized,C.PrepIsParked}
    class ReadOnly(PrepDriver):
        async def send_command(self,command,**kwargs):
            if type(command) not in allowed:raise RuntimeError('Read-only inspection')
            return await super().send_command(command,**kwargs)
        async def setup(self,**kw):raise RuntimeError('Setup prohibited')
        async def stop(self,**kw):raise RuntimeError('Transport close only')
    d=ReadOnly(deck=Deck(name='snapshot',size_x=300,size_y=430,size_z=200),
        io=HamiltonTCPClient(host='192.168.100.102',port=2000,read_timeout=8,write_timeout=5))
    try:
        await asyncio.wait_for(d._open(),20)
        return {cls.__name__:to_jsonable(await d.send_command(cls())) for cls in allowed}
    finally:await d._close()

if __name__=='__main__':
    h=HamiltonPrep();s=h.status(fresh=True)
    if s.get('serial')!='PRPGJ2494':raise RuntimeError('Unexpected instrument')
    print(json.dumps(asyncio.run(snapshot()),indent=2))
