"""Read the original door sensor via a verified named controller method."""
from probe_prep_coordinates import SOURCE
import sys
sys.path.insert(0, str(SOURCE))
from pylabrobot.hamilton.prep.driver import prep_commands as C

class PrepGetIsDoorClosed(C.PrepGetIsEnclosurePresent):
    # Same empty-request / padded-boolean-response shape, different status ID.
    command_id = 22

async def verify_door_method(driver):
    method = await driver.request_method_by_name('MLPrepRoot.MLPrep', 'GetIsDoorClosed')
    if method.interface_id != 1 or method.method_id != 22:
        raise RuntimeError('Door status method differs from the reviewed controller schema.')

async def read_interlocks(driver):
    door = (await driver.send_command(PrepGetIsDoorClosed(), read_timeout=1)).value
    enclosure = (await driver.send_command(C.PrepGetIsEnclosurePresent(), read_timeout=1)).value
    if door is not True or enclosure is not True:
        raise RuntimeError(f'Original interlocks not ready: door_closed={door}, enclosure={enclosure}')
    return {'isDoorClosed':door,'isEnclosurePresent':enclosure,'source':'direct_controller_status'}
