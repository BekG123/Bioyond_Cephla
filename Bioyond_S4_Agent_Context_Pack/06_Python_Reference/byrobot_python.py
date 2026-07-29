import json
import asyncio
import threading
import time
import socket
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Any, Callable, Tuple
from collections import defaultdict
import logging

# Enums
class CmdType(str, Enum):
    setSysVarI = "setSysVarI"
    getSysVarI = "getSysVarI"
    setSysParaI = "setSysParaI"
    getSysParaI = "getSysParaI"
    setSysParaF = "setSysParaF"
    getSysParaF = "getSysParaF"
    getJointInfo = "getJointInfo"
    getCtrlMode = "getCtrlMode"
    switchToAuto = "switchToAuto"
    switchToManual = "switchToManual"
    getEnableStatus = "getEnableStatus"
    remoteEnable = "remoteEnable"
    remoteDisable = "remoteDisable"
    getProgState = "getProgState"
    remoteStart = "remoteStart"
    remotePause = "remotePause"
    remoteStop = "remoteStop"
    remoteClearError = "remoteClearError"
    getRobotErr = "getRobotErr"
    getLuaAppStatus = "getLuaAppStatus"
    getZeroConfig = "getZeroConfig"
    moveBackwards = "moveBackwards"

class ModeType(IntEnum):
    Auto = 0
    Manual = 1

class LuaProgramState(IntEnum):
    Stopped = 0
    Running = 1
    Paused = 2

class ProgramControlCmdType(IntEnum):
    StartOrRecovery = 0
    Pause = 1
    Stop = 2

class ErrorType(IntEnum):
    ParseError = -32700

# Data classes
class SysVarIParam:
    def __init__(self, index: int, value: float):
        self.index = index
        self.value = value
    
    def to_dict(self):
        return {"index": self.index, "value": self.value}

class ErrorInfo:
    def __init__(self, err_code: int, err_msg: str):
        self.errCode = err_code
        self.errMsg = err_msg

class ReceiveRobotInfo:
    def __init__(self, data: dict):
        self.BRCAPI = data.get("BRCAPI")
        self.id = data.get("id")
        self.ret = data.get("ret")
        self.error = data.get("error")
        self.reply = data.get("reply")

# Thread-safe list implementation
class SafeList:
    def __init__(self):
        self._list = []
        self._lock = threading.Lock()
    
    def add(self, item):
        with self._lock:
            self._list.append(item)
    
    def count(self):
        with self._lock:
            return len(self._list)
    
    def count_all(self, predicate):
        with self._lock:
            return sum(1 for item in self._list if predicate(item))
    
    def find_last(self, predicate):
        with self._lock:
            for item in reversed(self._list):
                if predicate(item):
                    return item
            return None
    
    def remove_all(self, predicate):
        with self._lock:
            self._list = [item for item in self._list if not predicate(item)]

# Sequential number generator
class SequentialNumberGenerator:
    def __init__(self, max_value=2147483647):
        self._current = 0
        self._max_value = max_value
        self._lock = threading.Lock()
    
    def get_next_number(self):
        with self._lock:
            self._current += 1
            if self._current > self._max_value:
                self._current = 1
            return self._current

# Socket communication implementation
class SocketCommunication:
    def __init__(self):
        self.is_connected = False
        self.on_receive = None
        self._socket = None
        self._endpoint = None
        self._receive_thread = None
        self._stop_receive = False
        self.is_connected_action = None  # Callback for connection status changes
    
    def init(self, ip_address: str, port: int, receive_filter=None) -> bool:
        """Initialize socket connection parameters"""
        try:
            # Set server IP and port
            self._endpoint = (ip_address, port)
            # Create socket object
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            return True
        except Exception as ex:
            print(f"Initialization failed: {str(ex)}")
            return False
    
    def open(self, communication_timeout: int = 0) -> bool:
        """Open socket connection with optional timeout"""
        try:
            if communication_timeout > 0:
                self._socket.settimeout(communication_timeout)
            
            # Try to connect to server
            self._socket.connect(self._endpoint)
            
            if self._socket:
                self.is_connected = True
                # Trigger connection success callback
                if self.is_connected_action:
                    self.is_connected_action(True)
                
                # Start receive thread
                self._stop_receive = False
                self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
                self._receive_thread.start()
            
            return self.is_connected
            
        except socket.error as ex:
            print(f"Connection failed: {str(ex)} Endpoint: {self._endpoint[0]}:{self._endpoint[1]}")
            return False
    
    def send(self, data: bytes) -> bool:
        """Send data to server"""
        try:
            if self.is_connected and self._socket:
                # Send byte data
                self._socket.sendall(data)
                return True
            return False
        except socket.error as ex:
            print(f"Send failed: {str(ex)}")
            self.is_connected = False
            return False
    
    def receive(self, span: int = 0) -> List[int]:
        """Receive data from server"""
        received_data = []
        
        try:
            if self.is_connected and self._socket:
                # Set timeout if span is provided
                if span > 0:
                    self._socket.settimeout(span / 1000.0)  # Convert ms to seconds
                else:
                    self._socket.settimeout(None)  # Blocking mode
                
                buffer = self._socket.recv(1024)  # Receive up to 1024 bytes
                
                if buffer:
                    # Convert bytes to list of integers
                    received_data = list(buffer)
                    
                    # Trigger receive callback
                    if self.on_receive:
                        self.on_receive(received_data)
                else:
                    # Empty buffer means connection closed
                    self.is_connected = False
                    if self.is_connected_action:
                        self.is_connected_action(False)
                        
        except socket.timeout:
            # Timeout is normal in non-blocking mode
            pass
        except OSError as ex:
            # Windows specific socket errors
            if "10038" in str(ex):  # Socket operation on non-socket
                # Socket is already closed, just return
                self.is_connected = False
                return received_data
            elif self.is_connected:
                print(f"Receive failed: {str(ex)}")
                self.is_connected = False
        except socket.error as ex:
            if self.is_connected:
                print(f"Receive failed: {str(ex)}")
                self.is_connected = False
            
        return received_data
    
    def _receive_loop(self):
        """Background thread for continuous receiving"""
        while not self._stop_receive and self.is_connected:
            try:
                if not self._socket:
                    break
                self.receive()
            except socket.error as ex:
                if self.is_connected:
                    print(f"Receive loop socket error: {str(ex)}")
                break
            except Exception as ex:
                if self.is_connected:
                    print(f"Receive loop error: {str(ex)}")
                break
    
    def close(self) -> bool:
        """Close socket connection"""
        try:
            self._stop_receive = True
            
            if self._socket and self.is_connected:
                # Check if there's pending data
                self._socket.setblocking(False)
                try:
                    # Try to receive any remaining data
                    self._socket.recv(1024, socket.MSG_DONTWAIT)
                except:
                    pass
                
                # Shutdown socket
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                    
                # Close socket
                self._socket.close()
                self.is_connected = False
                
                # Trigger disconnect callback
                if self.is_connected_action:
                    self.is_connected_action(False)
                
                # Wait for receive thread to finish
                if self._receive_thread and self._receive_thread.is_alive():
                    self._receive_thread.join(timeout=1)
                    
            return True
            
        except socket.error as ex:
            print(f"Close failed: {str(ex)}")
            return False
    
    def send_to(self, target, data: bytes) -> bool:
        """Not implemented - for future UDP support"""
        raise NotImplementedError("SendTo method not implemented")

# Logging interface
class ILog:
    def debug(self, message: str): pass
    def info(self, message: str): pass
    def warn(self, message: str): pass
    def error(self, message: str): pass

class Log(ILog):
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)
    
    def debug(self, message: str):
        self.logger.debug(message)
    
    def info(self, message: str):
        self.logger.info(message)
    
    def warn(self, message: str):
        self.logger.warning(message)
    
    def error(self, message: str):
        self.logger.error(message)

# Main robot controller class
class BYRobotSample:
    _BRCAPI = "1.0"
    _MAXINDEX = 2147483647
    
    def __init__(self):
        self._is_inited = False
        self._error_infos = ""
        self._temp_err = ""
        self._set_sys_var_i_return_value = 1
        self._communication = SocketCommunication()
        self._receive_messages = SafeList()
        self._token_source = None
        self._generator = SequentialNumberGenerator(self._MAXINDEX)
        self._is_need_send_heart = True
        self.current_time = datetime.now()
        self._locker_for_send = threading.Lock()
        self._log = Log()
        self._heart_task = None
        
        # Start heartbeat
        #self._start_heartbeat()
    
    def connect(self, ip_address: str, port: int, communication_timeout: int = 0) -> int:
        """Connect to robot with given IP and port"""
        try:
            self._is_inited = True
            
            # Initialize socket communication
            if not self._communication.init(ip_address, port):
                self._log.error("Failed to initialize socket communication")
                return -1
            
            # Try to open connection
            if self._communication.open(communication_timeout):
                self._communication.on_receive = self._handle_receive_data
                self.clear_errors()
                self.change_lua_program_state(ProgramControlCmdType.Stop)
                self._prepare_robot()
                self._log.info("Robot connected successfully")
                return 0
            
            # If not immediately connected, wait up to 5 seconds
            timeout = datetime.now() + timedelta(seconds=5)
            
            while datetime.now() < timeout:
                if not self._communication.is_connected:
                    time.sleep(0.1)
                    continue
                else:
                    self._communication.on_receive = self._handle_receive_data
                    self.clear_errors()
                    self.change_lua_program_state(ProgramControlCmdType.Stop)
                    self._prepare_robot()
                    self._log.info("Robot connected successfully")
                    return 0
            
            self._log.error("Robot connection failed")
            return -1
            
        except Exception as e:
            self._is_inited = False
            if self._communication and self._communication.is_connected:
                self._communication.close()
            self._log.error(f"Robot connection failed: {str(e)}")
            return -1
    
    def disconnect(self) -> int:
        """Disconnect from robot"""
        try:
            if self._communication and self._communication.is_connected:
                ret = 0 if self._communication.close() else -1
                if ret == 0:
                    self._log.info("Robot connection closed")
                return ret
            else:
                self._log.info("Robot connection already closed, no need to close again")
                return 0
        except Exception as ex:
            self._log.error(f"Error occurred while closing robot connection: {str(ex)}")
            return -1
    
    def clear_errors(self, timeout: int = 5000) -> bool:
        """Clear robot errors"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._clear_errors_async(timeout))
        if not res:
            for i in range(1):
                res = loop.run_until_complete(self._clear_errors_async(timeout))
                if res:
                    break
        
        res = loop.run_until_complete(self._clear_errors_async(timeout))
        self._log.info(f"Robot clear errors result: {res}")
        return res
    
    def set_sys_var_i(self, sys_var_i_params: Dict[str, int], timeout: int = 5 * 60 * 1000) -> bool:
        """Set robot system variables"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._set_sys_var_i_async(sys_var_i_params, timeout))
        self._log.info(f"Robot set system variables {json.dumps(sys_var_i_params)}, result: {res}")
        return res
    
    def get_sys_var_i(self, indexes: List[int], timeout: int = 5 * 60 * 1000) -> List[SysVarIParam]:
        """Get robot system variables"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_sys_var_i_async(indexes, timeout))
        self._log.info(f"Robot get system variables result: {json.dumps([vars(r) for r in res] if res else None)}")
        return res
    
    def set_sys_para_i(self, sys_para_i_dics: Dict[str, int], timeout: int = 5 * 60 * 1000) -> bool:
        """Set robot integer system parameters"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._set_sys_para_i_async(sys_para_i_dics, timeout))
        self._log.info(f"Robot set system variables {json.dumps(sys_para_i_dics)}, result: {res}")
        return res
    
    def get_sys_para_i(self, indexes: List[int], timeout: int = 5 * 60 * 1000) -> List[SysVarIParam]:
        """Get robot integer system parameters"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_sys_para_i_async(indexes, timeout))
        self._log.debug(f"Robot get integer system parameters result: {json.dumps([vars(r) for r in res] if res else None)}")
        return res
    
    def set_sys_para_f(self, sys_para_f_dics: Dict[str, float], timeout: int = 5 * 60 * 1000) -> bool:
        """Set robot float system parameters"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._set_sys_para_f_async(sys_para_f_dics, timeout))
        self._log.info(f"Robot set float system parameters {json.dumps(sys_para_f_dics)}, result: {res}")
        return res
    
    def get_sys_para_f(self, indexes: List[int], timeout: int = 5 * 60 * 1000) -> List[SysVarIParam]:
        """Get robot float system parameters"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_sys_para_f_async(indexes, timeout))
        self._log.debug(f"Robot get float system parameters result: {json.dumps([vars(r) for r in res] if res else None)}")
        return res
    
    def get_joint_info(self, timeout: int = 5000) -> str:
        """Get robot current position info"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_joint_info_async(timeout))
        self._log.info(f"Robot get joint info result: {res}")
        return res
    
    def control_remote_enable(self, is_enable: bool, timeout: int = 5000) -> bool:
        """Control robot enable state"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._remote_enable_async(is_enable, timeout))
        self._log.info(f"Robot set enable {is_enable}, result: {res}")
        return res
    
    def get_is_lua_ready(self, timeout: int = 5000) -> bool:
        """Check if Lua is ready"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_is_lua_ready_async(timeout))
        if not res:
            self._log.info(f"Robot get Lua ready status result: {res}")
        else:
            self._log.debug(f"Robot get Lua ready status result: {res}")
        return res
    
    def change_lua_program_state(self, program_control_cmd_type: ProgramControlCmdType, timeout: int = 5000) -> bool:
        """Change Lua program state"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._change_lua_program_state_async(program_control_cmd_type, timeout))
        self._log.info(f"Robot set Lua program state {program_control_cmd_type}, result: {res}")
        return res
    
    # Private methods
    def _prepare_robot(self) -> int:
        """Prepare robot for operation"""
        mode = self._get_robot_mode()
        
        if mode != ModeType.Auto:
            if not self._change_mode(ModeType.Auto):
                return -1
        
        is_enabled = self._get_is_robot_enable()
        if is_enabled is None or not is_enabled:
            if not self.control_remote_enable(True):
                return -1
        
        pro_state = self._get_lua_program_state()
        if pro_state != LuaProgramState.Running:
            if not self.change_lua_program_state(ProgramControlCmdType.StartOrRecovery):
                return -1
            self._check_lua_ready_in_period_time()
        
        return 0
    
    def _get_robot_mode(self, timeout: int = 5000) -> Optional[ModeType]:
        """Get robot manual/auto mode"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_robot_mode_async(timeout))
        if res is None or res != ModeType.Auto:
            self._log.info(f"Robot get mode result: {res}")
        else:
            self._log.debug(f"Robot get mode result: {res}")
        return res
    
    def _change_mode(self, mode_type: ModeType, timeout: int = 5000) -> bool:
        """Change robot mode"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._change_mode_async(mode_type, timeout))
        self._log.info(f"Robot set mode {mode_type}, result: {res}")
        return res
    
    def _get_is_robot_enable(self, timeout: int = 5000) -> Optional[bool]:
        """Get robot enable status"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_is_robot_enable_async(timeout))
        if res is None or not res:
            self._log.info(f"Robot get enable status result: {res}")
        else:
            self._log.debug(f"Robot get enable status result: {res}")
        return res
    
    def _get_lua_program_state(self, timeout: int = 5000) -> Optional[LuaProgramState]:
        """Get Lua program state"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        res = loop.run_until_complete(self._get_lua_program_state_async(timeout))
        if res is None or res != LuaProgramState.Running:
            self._log.info(f"Robot get Lua running state result: {res}")
        else:
            self._log.debug(f"Robot get Lua running state result: {res}")
        return res
    
    def _check_lua_ready_in_period_time(self, period_time: int = 5000) -> bool:
        """Check if Lua is ready within period time"""
        start_time = datetime.now()
        
        while True:
            if self.get_is_lua_ready(500):
                return True
            
            if (datetime.now() - start_time).total_seconds() * 1000 > period_time:
                return False
            
            time.sleep(0.1)
    
    def _handle_receive_data(self, data: List[int]):
        """Handle received data"""
        try:
            info = bytes(data).decode('utf-8')
            info = info.rstrip('\n')
            
            if '"ret":[{"errCode":null,"errMsg":null}' not in info:
                self._log.debug(f"Robot received message: {info}")
            
            receive_data = json.loads(info)
            
            if receive_data.get("BRCAPI") != self._BRCAPI:
                self._log.warn(f"Robot received message {info}, BRCAPI doesn't match current driver support, received BRCAPI: {receive_data.get('BRCAPI')}, driver defined: {self._BRCAPI}")
                return
            
            if receive_data.get("id") == -1:
                self._log.warn(f"Invalid message: {info}")
                return
            
            receive_robot_info = ReceiveRobotInfo(receive_data)
            self._receive_messages.add(receive_robot_info)
            
        except Exception as ex:
            self._log.error(f"Robot error processing received message {bytes(data).decode('utf-8')}: {str(ex)}")
    
    def _start_heartbeat(self):
        """Start heartbeat thread"""
        self._heart_task = threading.Thread(target=self._send_heart_thread, daemon=True)
        self._heart_task.start()
    
    def _send_heart_thread(self):
        """Heartbeat thread function"""
        time.sleep(3)
        
        while True:
            try:
                if self._communication and self._communication.is_connected and self._is_need_send_heart:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self._get_error_info_async(5000))
            except Exception as ex:
                self._log.error(f"Robot heartbeat error: {str(ex)}")
            
            time.sleep(0.8)
    
    def _generate_command(self, cmd_type: CmdType, param: Any) -> Tuple[int, str]:
        """Generate command to send"""
        id_num = self._generator.get_next_number()
        
        command = {
            "BRCAPI": self._BRCAPI,
            "cmd": cmd_type.value,
            "params": param,
            "id": id_num
        }
        
        json_str = json.dumps(command)
        return id_num, json_str
    
    def _send(self, info: str) -> bool:
        """Send message to robot"""
        if self._communication and self._communication.is_connected:
            with self._locker_for_send:
                if '"cmd":"getRobotErr"' not in info:
                    self._log.debug(f"Sending message: {info}")
                
                res = self._communication.send((info + "\n").encode('utf-8'))
                time.sleep(0.2)
                return res
        
        self._log.error(f"Robot communication object is null or connection status is wrong, communication={self._communication}, send failed")
        return False
    
    def _get_request_need_return_times(self, cmd_type: CmdType) -> int:
        """Get how many return messages needed for different commands"""
        two_returns = [
            CmdType.setSysVarI, CmdType.switchToAuto, CmdType.switchToManual,
            CmdType.remoteEnable, CmdType.remoteDisable, CmdType.remoteStart,
            CmdType.remotePause, CmdType.remoteStop, CmdType.remoteClearError,
            CmdType.moveBackwards
        ]
        
        return 2 if cmd_type in two_returns else 1
    
    # Async methods
    async def _send_and_wait_response_async(self, cmd_type: CmdType, param: Any, timeout: int = 5 * 60 * 1000) -> Optional[ReceiveRobotInfo]:
        """Send command and wait for response"""
        id_num, json_str = self._generate_command(cmd_type, param)
        
        if not self._send(json_str):
            return None
        
        return await self._find_response_async(id_num, timeout, cmd_type, self._get_request_need_return_times(cmd_type))
    
    async def _find_response_async(self, id_num: int, timeout: int, cmd_type: CmdType, return_times: int = 1) -> Optional[ReceiveRobotInfo]:
        """Find response for given id"""
        start_time = datetime.now()
        
        while True:
            if self._communication.is_connected:
                if (datetime.now() - start_time).total_seconds() * 1000 > timeout:
                    self._log.warn(f"Waiting for message {id_num} timeout")
                    return None
                
                count = self._receive_messages.count_all(lambda x: x.id == id_num)
                error_msg = self._receive_messages.find_last(lambda x: x.id == id_num and x.error is not None)
                
                if self._receive_messages.count() > 0 and (count == return_times or error_msg):
                    temp = self._receive_messages.find_last(lambda x: x.id == id_num)
                    if temp:
                        self._receive_messages.remove_all(lambda x: x.id == id_num)
                        return temp
                
                if cmd_type == CmdType.setSysVarI:
                    if self._error_infos:
                        return None
                    temp = self._receive_messages.find_last(lambda x: x.id == id_num)
                    if not temp:
                        return None
                
                await asyncio.sleep(0.1)
            else:
                return None
    
    async def _clear_errors_async(self, timeout: int = 5000) -> bool:
        """Clear errors async"""
        t = await self._send_and_wait_response_async(CmdType.remoteClearError, None, timeout)
        
        if t:
            json_mess = json.dumps(vars(t))
            if "CmdDone" in json_mess:
                return True
            else:
                self._log.warn(f"Remote clear error failed, return field doesn't contain CmdDone, details: {json_mess}")
                return False
        else:
            self._log.warn("Robot send remote clear error failed")
            return False
    
    async def _set_sys_var_i_async(self, sys_var_i_dics: Dict[str, int], timeout: int = 5 * 60 * 1000) -> bool:
        """Set system variables async"""
        if not sys_var_i_dics:
            self._log.warn("Robot set system variables failed, system variable info is empty")
            return False
        
        sys_var_i_params = []
        for key, value in sys_var_i_dics.items():
            try:
                index = int(key)
                sys_var_i_params.append(SysVarIParam(index, value).to_dict())
            except ValueError:
                self._log.warn(f"Robot set system variables failed, system variable ID: {key} is not a number")
                return False
        
        t = await self._send_and_wait_response_async(CmdType.setSysVarI, sys_var_i_params, timeout)
        
        try:
            if t is None:
                if self._error_infos:
                    if "Emergency stop" in self._error_infos:
                        raise Exception(self._error_infos)
                    if "Collision" in self._error_infos:
                        raise Exception(self._error_infos)
                    else:
                        raise Exception("Robot execute command exception")
        except Exception as ex:
            self._log.error(f"Robot caught exception: {str(ex)}")
            input()  # Equivalent to Console.ReadLine()
        
        if t:
            json_mess = json.dumps(vars(t))
            if f'"value":{self._set_sys_var_i_return_value}' in json_mess:
                return True
            else:
                return False
        else:
            self._log.warn("Robot send set system variables failed!")
            return False
    
    async def _get_sys_var_i_async(self, indexes: List[int], timeout: int = 5 * 60 * 1000) -> Optional[List[SysVarIParam]]:
        """Get system variables async"""
        infos = [{"index": idx} for idx in indexes]
        
        t = await self._send_and_wait_response_async(CmdType.getSysVarI, infos, timeout)
        
        if t:
            if isinstance(t.ret, list):
                return [SysVarIParam(item["index"], item["value"]) for item in t.ret]
        else:
            self._log.warn("Robot get system variables failed")
        
        return None
    
    async def _set_sys_para_i_async(self, sys_para_i_dics: Dict[str, int], timeout: int = 5 * 60 * 1000) -> bool:
        """Set integer system parameters async"""
        if not sys_para_i_dics:
            self._log.warn("Robot set system variables failed, system variable info is empty")
            return False
        
        sys_para_i_params = []
        for key, value in sys_para_i_dics.items():
            try:
                index = int(key)
                sys_para_i_params.append(SysVarIParam(index, value).to_dict())
            except ValueError:
                self._log.warn(f"Robot set system variables failed, system variable ID: {key} is not a number")
                return False
        
        t = await self._send_and_wait_response_async(CmdType.setSysParaI, sys_para_i_params, timeout)
        
        if t:
            return t.error is None
        else:
            self._log.warn("Robot set integer system parameter variables failed!")
            return False
    
    async def _get_sys_para_i_async(self, indexes: List[int], timeout: int = 5 * 60 * 1000) -> Optional[List[SysVarIParam]]:
        """Get integer system parameters async"""
        infos = [{"index": idx} for idx in indexes]
        
        t = await self._send_and_wait_response_async(CmdType.getSysParaI, infos, timeout)
        
        if t:
            if isinstance(t.ret, list):
                return [SysVarIParam(item["index"], item["value"]) for item in t.ret]
        else:
            self._log.warn("Robot get integer system parameters failed")
        
        return None
    
    async def _set_sys_para_f_async(self, sys_para_f_dics: Dict[str, float], timeout: int = 5 * 60 * 1000) -> bool:
        """Set float system parameters async"""
        if not sys_para_f_dics:
            self._log.warn("Robot set float system parameters failed, system variable info is empty")
            return False
        
        sys_para_f_params = []
        for key, value in sys_para_f_dics.items():
            try:
                index = int(key)
                sys_para_f_params.append(SysVarIParam(index, value).to_dict())
            except ValueError:
                self._log.warn(f"Robot set float system parameters failed, system parameter ID: {key} is not a number")
                return False
        
        t = await self._send_and_wait_response_async(CmdType.setSysParaF, sys_para_f_params, timeout)
        
        if t:
            return t.error is None
        else:
            self._log.warn("Robot set float system parameters failed!")
            return False
    
    async def _get_sys_para_f_async(self, indexes: List[int], timeout: int = 5 * 60 * 1000) -> Optional[List[SysVarIParam]]:
        """Get float system parameters async"""
        infos = [{"index": idx} for idx in indexes]
        
        t = await self._send_and_wait_response_async(CmdType.getSysParaF, infos, timeout)
        
        if t:
            if isinstance(t.ret, list):
                return [SysVarIParam(item["index"], item["value"]) for item in t.ret]
        else:
            self._log.warn("Robot get float system parameters failed")
        
        return None
    
    async def _get_joint_info_async(self, timeout: int = 5000) -> str:
        """Get joint info async"""
        t = await self._send_and_wait_response_async(CmdType.getJointInfo, None, timeout)
        
        if t:
            json_mess = json.dumps(t.ret)
            if "joints" in json_mess:
                return json_mess
            else:
                self._log.warn(f"Get joint info failed, return field doesn't contain joints, details: {json.dumps(vars(t))}")
                return ""
        else:
            self._log.warn("Robot get joint info failed")
            return ""
    
    async def _get_robot_mode_async(self, timeout: int = 500) -> Optional[ModeType]:
        """Get robot mode async"""
        t = await self._send_and_wait_response_async(CmdType.getCtrlMode, None, timeout)
        
        if t and hasattr(t, 'ret') and isinstance(t.ret, dict):
            value = t.ret.get('value', -1)
            if 0 <= value <= 2:
                return ModeType(value)
            else:
                self._log.warn(f"Robot get mode failed, details: {json.dumps(vars(t))}")
                return None
        else:
            self._log.warn("Robot get mode failed")
            return None
    
    async def _change_mode_async(self, mode_type: ModeType, timeout: int = 5000) -> bool:
        """Change mode async"""
        cmd_type = CmdType.switchToAuto if mode_type == ModeType.Auto else CmdType.switchToManual
        
        t = await self._send_and_wait_response_async(cmd_type, None, timeout)
        
        if t:
            json_mess = json.dumps(vars(t))
            if "CmdDone" in json_mess:
                return True
            else:
                self._log.warn(f"Robot mode switch failed, return field doesn't contain CmdDone, details: {json_mess}")
                return False
        else:
            self._log.warn(f"Robot mode switch {mode_type} failed")
            return False
    
    async def _get_is_robot_enable_async(self, timeout: int = 500) -> Optional[bool]:
        """Get robot enable status async"""
        t = await self._send_and_wait_response_async(CmdType.getEnableStatus, None, timeout)
        
        if t and hasattr(t, 'ret') and isinstance(t.ret, dict):
            value = t.ret.get('value', -1)
            if 0 <= value <= 1:
                return value == 1
            else:
                self._log.warn(f"Robot get enable status failed, details: {json.dumps(vars(t))}")
                return None
        else:
            self._log.warn("Robot get enable status failed")
            return None
    
    async def _remote_enable_async(self, is_enable: bool, timeout: int = 5000) -> bool:
        """Remote enable async"""
        cmd_type = CmdType.remoteEnable if is_enable else CmdType.remoteDisable
        
        t = await self._send_and_wait_response_async(cmd_type, None, timeout)
        
        if t:
            json_mess = json.dumps(vars(t))
            if "CmdDone" in json_mess:
                return True
            else:
                self._log.warn(f"Robot enable switch failed, return field doesn't contain CmdDone, details: {json_mess}")
                return False
        else:
            self._log.warn("Robot enable switch failed")
            return False
    
    async def _get_lua_program_state_async(self, timeout: int = 500) -> Optional[LuaProgramState]:
        """Get Lua program state async"""
        t = await self._send_and_wait_response_async(CmdType.getProgState, None, timeout)
        
        if t and hasattr(t, 'ret') and isinstance(t.ret, dict):
            value = t.ret.get('value', -1)
            if 0 <= value <= 3:
                return LuaProgramState(value)
            else:
                self._log.warn(f"Robot get Lua running state failed, details: {json.dumps(vars(t))}")
                return None
        else:
            return None
    
    async def _change_lua_program_state_async(self, program_control_cmd_type: ProgramControlCmdType, timeout: int = 5000) -> bool:
        """Change Lua program state async"""
        self._log.info(f"Robot set Lua program running state to {program_control_cmd_type}")
        
        cmd_map = {
            ProgramControlCmdType.StartOrRecovery: CmdType.remoteStart,
            ProgramControlCmdType.Pause: CmdType.remotePause,
            ProgramControlCmdType.Stop: CmdType.remoteStop
        }
        
        cmd_type = cmd_map.get(program_control_cmd_type, CmdType.getCtrlMode)
        
        t = await self._send_and_wait_response_async(cmd_type, None, timeout)
        
        if t:
            json_mess = json.dumps(vars(t))
            if "CmdDone" in json_mess:
                return True
            else:
                self._log.warn(f"Robot send Lua program state failed, return field doesn't contain CmdDone, details: {json_mess}")
                return False
        else:
            self._log.warn(f"Robot send Lua program state {program_control_cmd_type} failed")
            return False
    
    async def _get_is_lua_ready_async(self, timeout: int = 500) -> bool:
        """Get if Lua is ready async"""
        t = await self._send_and_wait_response_async(CmdType.getLuaAppStatus, None, timeout)
        
        if t and hasattr(t, 'ret') and isinstance(t.ret, dict):
            value = t.ret.get('value', -1)
            if 0 <= value <= 1:
                return value == 1
            else:
                self._log.warn(f"[{self.current_time.strftime('%Y-%m-%d %H:%M:%S')}] Robot get Lua ready status failed, details: {json.dumps(vars(t))}")
                return False
        else:
            self._log.warn(f"[{self.current_time.strftime('%Y-%m-%d %H:%M:%S')}] Robot get Lua ready status failed")
            return False
    
    async def _get_error_info_async(self, timeout: int = 5000) -> Optional[List[ErrorInfo]]:
        """Get error info async"""
        try:
            temp = await self._send_and_wait_response_async(CmdType.getRobotErr, None, timeout)
        except Exception as ex:
            self._log.error(f"Robot get error info failed: {str(ex)}")
            return None
        
        if temp:
            json_mess = json.dumps(vars(temp))
            
            if '{"errCode":null,"errMsg":null}' in json_mess:
                self._error_infos = ""
                return None
            elif '"error":{' in json_mess:
                self._log.warn(f"Send command error, get error info failed, command type: {CmdType.getRobotErr}, error info: {json_mess}")
                return None
            else:
                errs = []
                if isinstance(temp.ret, list):
                    for item in temp.ret:
                        if isinstance(item, dict):
                            errs.append(ErrorInfo(item.get("errCode"), item.get("errMsg")))
                
                self._error_infos = ""
                temp_errs = ""
                
                for item in errs:
                    temp_errs += f"Error code: {item.errCode}. Error description: {item.errMsg}\r\n"
                
                if any(err.errCode in [3611, 3608] for err in errs):
                    self._error_infos = "Emergency stop button triggered"
                elif any(err.errCode == 3873 for err in errs):
                    self._error_infos = "Robot collision occurred"
                else:
                    self._error_infos = "Unknown exception"
                
                if self._error_infos == self._temp_err:
                    return errs
                
                self._temp_err = self._error_infos
                self._log.error(f"Got error info: {temp_errs} {self._error_infos}")
                return errs
        else:
            self._log.warn(f"Get error info failed! {json.dumps(vars(temp)) if temp else None}")
            return None