"""Canonical Cellvis reference/live image preparation, without hardware access.

The commissioned reference exists only as JPEG82 frames. Decode each once;
convert fresh raw frames through that same encoding before the five-frame
median. Do not recompress the archived JPEGs or compress an already-made median.
Raw live images are still retained separately as evidence.
"""
import cv2
import numpy as np

PIPELINE_ID='cellvis24-jpeg82-bgr-median5-v1'
JPEG_QUALITY=82
SHAPE=(2048,3072,3)

def validate(frame):
    if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8 or frame.shape!=SHAPE:
        raise ValueError('Cellvis requires native3072x2048 uint8 BGR images.')
    return frame

def decode_reference(data):
    if not isinstance(data,bytes) or not data.startswith(b'\xff\xd8'):
        raise ValueError('Expected the archived reference JPEG bytes.')
    return validate(cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR))

def prepare_raw(frame):
    validate(frame)
    ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,JPEG_QUALITY])
    if not ok:raise ValueError('Cellvis image encoding failed.')
    return decode_reference(encoded.tobytes())

def median5(prepared):
    if len(prepared)!=5:raise ValueError('Exactly five prepared frames required.')
    for frame in prepared:validate(frame)
    return np.median(prepared,axis=0).astype(np.uint8)

def metadata():
    return dict(id=PIPELINE_ID,jpeg_quality=JPEG_QUALITY,frame_count=5,
                resolution=[3072,2048],channels='BGR',opencv_version=cv2.__version__)
