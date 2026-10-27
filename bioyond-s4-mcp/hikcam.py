"""HIKROBOT / MVS GigE Vision camera capture for the Bioyond S4 cell.

Uses the MVS SDK's Python bindings (installed with the MVS client). The
camera sits on the same Ethernet segment as the robot controller. GigE
cameras allow ONE control connection at a time — close the MVS client's
live feed before capturing here, and call release() to give it back.

Like vision.py (the Arducam), this module only CAPTURES — detection is done
by the agent viewing the images.
"""

from __future__ import annotations

import os
import sys
from ctypes import POINTER, byref, cast, memset, sizeof, c_ubyte
from typing import Optional

import numpy as np

_MVIMPORT_CANDIDATES = [
    os.environ.get("BIOYOND_MVIMPORT", ""),
    (os.getenv("MVCAM_COMMON_RUNENV") or "") + r"\Samples\Python\MvImport",
    r"C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport",
]

_sdk_loaded = False


def _load_sdk() -> None:
    global _sdk_loaded
    if _sdk_loaded:
        return
    for cand in _MVIMPORT_CANDIDATES:
        if cand and os.path.isfile(os.path.join(cand, "MvCameraControl_class.py")):
            if cand not in sys.path:
                sys.path.append(cand)
            break
    else:
        raise HikError(
            "MVS Python SDK not found — is the MVS client installed? "
            f"Looked in: {[c for c in _MVIMPORT_CANDIDATES if c]}"
        )
    global mv  # noqa: PLW0603
    import MvCameraControl_class as mv  # type: ignore  # noqa: E402
    mv.MvCamera.MV_CC_Initialize()
    _sdk_loaded = True


class HikError(Exception):
    pass


def _gige_ip(dev_info) -> str:
    ip = dev_info.SpecialInfo.stGigEInfo.nCurrentIp
    return f"{(ip >> 24) & 0xFF}.{(ip >> 16) & 0xFF}.{(ip >> 8) & 0xFF}.{ip & 0xFF}"


def _c_str(arr) -> str:
    out = ""
    for ch in arr:
        if ch == 0:
            break
        out += chr(ch)
    return out


def enumerate_devices() -> list[dict]:
    """List GigE Vision devices visible on the network."""
    _load_sdk()
    dev_list = mv.MV_CC_DEVICE_INFO_LIST()
    ret = mv.MvCamera.MV_CC_EnumDevices(mv.MV_GIGE_DEVICE, dev_list)
    if ret != 0:
        raise HikError(f"device enumeration failed (0x{ret:x})")
    out = []
    for i in range(dev_list.nDeviceNum):
        info = cast(dev_list.pDeviceInfo[i], POINTER(mv.MV_CC_DEVICE_INFO)).contents
        gi = info.SpecialInfo.stGigEInfo
        out.append({
            "index": i,
            "model": _c_str(gi.chModelName),
            "serial": _c_str(gi.chSerialNumber),
            "ip": _gige_ip(info),
            "user_name": _c_str(gi.chUserDefinedName),
        })
    return out


class HikCamera:
    def __init__(self) -> None:
        self._cam = None
        self._payload = 0
        self.info: Optional[dict] = None

    @property
    def is_open(self) -> bool:
        return self._cam is not None

    def open(self) -> None:
        if self.is_open:
            return
        _load_sdk()
        want_ip = os.environ.get("BIOYOND_HIKCAM_IP", "")
        dev_list = mv.MV_CC_DEVICE_INFO_LIST()
        ret = mv.MvCamera.MV_CC_EnumDevices(mv.MV_GIGE_DEVICE, dev_list)
        if ret != 0 or dev_list.nDeviceNum == 0:
            raise HikError(
                "no GigE camera found on the network (enumeration "
                f"ret=0x{ret:x}, count={dev_list.nDeviceNum})"
            )
        chosen = None
        for i in range(dev_list.nDeviceNum):
            info = cast(dev_list.pDeviceInfo[i], POINTER(mv.MV_CC_DEVICE_INFO)).contents
            if not want_ip or _gige_ip(info) == want_ip:
                chosen = (i, info)
                break
        if chosen is None:
            raise HikError(
                f"no GigE camera with IP {want_ip}; found: {enumerate_devices()}"
            )
        i, info = chosen
        cam = mv.MvCamera()
        if cam.MV_CC_CreateHandle(info) != 0:
            raise HikError("MV_CC_CreateHandle failed")
        ret = cam.MV_CC_OpenDevice(mv.MV_ACCESS_Exclusive, 0)
        if ret != 0:
            cam.MV_CC_DestroyHandle()
            raise HikError(
                f"could not open the camera (0x{ret:x}) — it is probably in "
                "use by the MVS client; close the MVS live view and retry"
            )
        # optimal GigE packet size reduces frame corruption
        psize = cam.MV_CC_GetOptimalPacketSize()
        if psize > 0:
            cam.MV_CC_SetIntValue("GevSCPSPacketSize", psize)
        cam.MV_CC_SetEnumValue("TriggerMode", 0)  # free-run
        # Apply on every connection, without relying on the last MVS session.
        ret = cam.MV_CC_SetBoolValue("GammaEnable", False)
        if ret != 0:
            cam.MV_CC_CloseDevice()
            cam.MV_CC_DestroyHandle()
            raise HikError(f"could not disable GammaEnable (0x{ret:x})")
        if cam.MV_CC_StartGrabbing() != 0:
            cam.MV_CC_CloseDevice()
            cam.MV_CC_DestroyHandle()
            raise HikError("MV_CC_StartGrabbing failed")
        gi = info.SpecialInfo.stGigEInfo
        self.info = {"model": _c_str(gi.chModelName), "ip": _gige_ip(info),
                     "serial": _c_str(gi.chSerialNumber)}
        self._cam = cam

    def capture(self, timeout_ms: int = 3000) -> np.ndarray:
        """Grab one frame and return it as a BGR numpy array."""
        self.open()
        cam = self._cam
        frame_out = mv.MV_FRAME_OUT()
        memset(byref(frame_out), 0, sizeof(frame_out))
        ret = cam.MV_CC_GetImageBuffer(frame_out, timeout_ms)
        if ret != 0 or not frame_out.pBufAddr:
            raise HikError(f"no frame within {timeout_ms} ms (0x{ret:x})")
        try:
            fi = frame_out.stFrameInfo
            w, h = fi.nWidth, fi.nHeight
            dst_size = w * h * 3
            dst = (c_ubyte * dst_size)()
            try:
                conv = mv.MV_CC_PIXEL_CONVERT_PARAM_EX()
                memset(byref(conv), 0, sizeof(conv))
                conv.nWidth, conv.nHeight = w, h
                conv.pSrcData = frame_out.pBufAddr
                conv.nSrcDataLen = fi.nFrameLenEx if hasattr(fi, "nFrameLenEx") else fi.nFrameLen
                conv.enSrcPixelType = fi.enPixelType
                conv.enDstPixelType = mv.PixelType_Gvsp_BGR8_Packed
                conv.pDstBuffer = dst
                conv.nDstBufferSize = dst_size
                ret = cam.MV_CC_ConvertPixelTypeEx(conv)
            except AttributeError:
                conv = mv.MV_CC_PIXEL_CONVERT_PARAM()
                memset(byref(conv), 0, sizeof(conv))
                conv.nWidth, conv.nHeight = w, h
                conv.pSrcData = frame_out.pBufAddr
                conv.nSrcDataLen = fi.nFrameLen
                conv.enSrcPixelType = fi.enPixelType
                conv.enDstPixelType = mv.PixelType_Gvsp_BGR8_Packed
                conv.pDstBuffer = dst
                conv.nDstBufferSize = dst_size
                ret = cam.MV_CC_ConvertPixelType(conv)
            if ret != 0:
                raise HikError(f"pixel conversion failed (0x{ret:x})")
            arr = np.frombuffer(dst, dtype=np.uint8, count=dst_size)
            return arr.reshape(h, w, 3).copy()
        finally:
            cam.MV_CC_FreeImageBuffer(frame_out)

    def release(self) -> None:
        if self._cam is not None:
            try:
                self._cam.MV_CC_StopGrabbing()
                self._cam.MV_CC_CloseDevice()
                self._cam.MV_CC_DestroyHandle()
            finally:
                self._cam = None
                self.info = None
