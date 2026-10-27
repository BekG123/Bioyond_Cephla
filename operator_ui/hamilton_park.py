"""One native PrepPark command, owned and confirmed through Lacry."""
import asyncio
from pathlib import Path
import subprocess
import sys
import time

from researcher_teaching import TeachingError

SOURCE=Path(__file__).resolve().parent/'tmp/prep-jog-audit'
PIN='fc5ae129c39ef645a2a11234dce97f933a317a9c'


def driver_types():
    revision=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
    if revision!=PIN:raise TeachingError('Hamilton parking toolkit changed; developer review required.')
    if str(SOURCE) not in sys.path:sys.path.insert(0,str(SOURCE))
    from pylabrobot.hamilton.prep.driver.master import PrepDriver
    from pylabrobot.hamilton.prep.driver import prep_commands as commands
    from pylabrobot.hamilton.transport.tcp.tcp import HamiltonTCPClient
    from pylabrobot.resources.deck import Deck
    return PrepDriver,commands,HamiltonTCPClient,Deck


def preflight(adapter):
    # This native controller address belongs to the commissioned local Prep.
    settings=adapter.settings()
    if (settings.get('serial_number')!='PRPGD2427' or
            settings.get('base_url','').rstrip('/')!='http://192.168.100.101/NimbusLite/api/v1'):
        raise TeachingError('Review the native controller connection for this Hamilton before parking.')
    # Parking is an explicit native command, not an initialization sequence.
    # Let the controller accept or reject it from its current state; do not
    # invent axis references or automatically initialize on rejection.
    state=adapter.preflight(initialized=False)
    sensors=adapter.call('GET','service-software-api/sensor-status')
    if sensors.get('isDoorClosed') is not True or sensors.get('isEnclosurePresent') is not True:
        raise TeachingError('Close Hamilton’s door before parking.')
    if adapter.call('GET','service-software-api/has-tips') is not False:
        raise TeachingError('Remove Hamilton’s attached tips or tools before parking.')
    verification=adapter.call('GET','verification/status')
    if any(verification.get(k) for k in ('isWorkflowInProgress','isRunInProgress','isServiceRoutineInProgress')):
        raise TeachingError('A Hamilton service routine is still active.')
    return state


async def native_park(adapter,ticket,stopped,baseline):
    Driver,C,TCP,Deck=driver_types()
    class ParkDriver(Driver):
        async def send_command(self,command,**kwargs):
            if type(command) not in (C.PrepPark,C.PrepMethodAbort):
                raise TeachingError('Command outside the parking allowlist.')
            adapter.journal(ticket,'native_command',dict(name=type(command).__name__))
            return await super().send_command(command,**kwargs)
        async def setup(self,**kwargs):raise TeachingError('Automatic initialization is disabled.')
        async def stop(self,**kwargs):raise TeachingError('Use transport-only close.')
    def make():
        return ParkDriver(deck=Deck(name='park',size_x=300,size_y=400,size_z=200),
            io=TCP(host='192.168.100.102',port=2000,read_timeout=60,write_timeout=5))
    driver=make();command=None
    try:
        await asyncio.wait_for(driver._open(),20)
        await asyncio.to_thread(preflight,adapter)
        if stopped():raise TeachingError('Hamilton parking cancelled before motion.')
        ticket['write_attempted']=True
        command=asyncio.create_task(driver.send_command(C.PrepPark(),read_timeout=60))
        deadline=time.monotonic()+65
        while not command.done():
            await asyncio.wait({command},timeout=.25)
            if stopped():
                abort=make()
                try:
                    await asyncio.wait_for(abort._open(),10)
                    await asyncio.wait_for(abort.send_command(C.PrepMethodAbort(),read_timeout=5),7)
                finally:await abort._close()
                raise TeachingError('Hamilton parking stop requested. Inspect its position before retrying.')
            if time.monotonic()>deadline:raise TeachingError('Hamilton parking timed out; inspect its position.')
            await asyncio.to_thread(adapter.guard_errors,ticket,baseline)
        await command
        adapter.journal(ticket,'native_response',dict(name='PrepPark',acknowledged=True))
    finally:
        if command is not None and not command.done():
            command.cancel()
            await asyncio.gather(command,return_exceptions=True)
        await driver._close()


def run(adapter,stopped,progress,sender=native_park):
    preflight(adapter)
    with adapter.owned('park') as ticket:
        original_stopped=stopped
        stopped=lambda: original_stopped() or ticket.get('park_stop_requested',False)
        state=preflight(adapter)
        ticket.update(status='running',step='park')
        if stopped():raise TeachingError('Hamilton parking cancelled before motion.')
        if adapter.call('GET','service-software-api/is-parked') is True:
            ticket['status']='completed'
            adapter.journal(ticket,'outcome',dict(status='completed',already_parked=True))
            return dict(ok=True,completed_steps=['park'],already_parked=True)
        baseline={x['id'] for x in adapter.call('GET','errors?offset=0&limit=30').get('items',[])}
        progress(dict(state,message='Parking Hamilton.',step='park',completed_steps=[]))
        asyncio.run(sender(adapter,ticket,stopped,baseline))
        adapter.guard_errors(ticket,baseline)
        state=adapter.status(fresh=True)
        if (stopped() or not state.get('connected') or state.get('global_state')!='Idle'
                or state.get('run',{}).get('isRunInProgress') or state.get('pending_errors')
                or adapter.call('GET','service-software-api/is-parked') is not True):
            raise TeachingError('Hamilton parking was not confirmed. Inspect the instrument; no retry was sent.')
        ticket['status']='completed'
        adapter.journal(ticket,'outcome',dict(status='completed',parked=True))
        return dict(ok=True,completed_steps=['park'],parked=True)
