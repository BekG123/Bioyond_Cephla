"""Image-only whole-plate similarity initializer; not a pose acceptance test."""
import cv2
import numpy as np


def rotation_seed(tracker,image):
    signal=tracker.anchor.signal(tracker.anchor.gray(image))
    low=np.floor(tracker.anchor.corners.min(axis=0)).astype(int)
    high=np.ceil(tracker.anchor.corners.max(axis=0)).astype(int)
    x,y=low;right,bottom=high
    template=tracker.anchor.reference_signal[y:bottom,x:right]
    height,width=template.shape
    center=((width-1)/2.,(height-1)/2.)
    small=cv2.resize(signal,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA)
    scales=np.linspace(.85,1.10,11) if tracker.template_scale_search else [1.]

    def candidate(angle,scale,coarse):
        m=cv2.getRotationMatrix2D(center,float(angle),float(scale))
        corners=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],float)
        q=corners@m[:,:2].T+m[:,2]
        lower=np.floor(q.min(axis=0));upper=np.ceil(q.max(axis=0))
        m[:,2]-=lower
        size=tuple((upper-lower+1).astype(int))
        if size[0]>signal.shape[1] or size[1]>signal.shape[0]:return None
        rotated=cv2.warpAffine(template,m,size,flags=cv2.INTER_LINEAR)
        search=small if coarse else signal
        if coarse:rotated=cv2.resize(rotated,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA)
        scores=cv2.matchTemplate(search,rotated,cv2.TM_CCOEFF_NORMED)
        scores=np.where(np.isfinite(scores),scores,-1.)
        _,score,_,location=cv2.minMaxLoc(scores)
        return score,location,m,scores,angle,scale

    candidates=[candidate(a,s,True) for a in np.arange(-6.,6.01,1.) for s in scales]
    candidates=[c for c in candidates if c is not None]
    if not candidates:return None,None
    coarse=max(candidates,key=lambda c:c[0])
    # Refine the image-measured similarity, not a robot-motion prediction.
    fine_scales=np.arange(max(.85,coarse[5]-.015),min(1.10,coarse[5]+.015)+.001,.005) if tracker.template_scale_search else [1.]
    candidates=[candidate(a,s,False) for a in np.arange(max(-6.,coarse[4]-.5),min(6.,coarse[4]+.5)+.01,.25) for s in fine_scales]
    candidates=[c for c in candidates if c is not None]
    raw_score,location,m,scores,angle,scale=max(candidates,key=lambda c:c[0])
    # Keep the image-selected transform; evaluate confidence only on pixels
    # that existed in the source rectangle, excluding artificial padding.
    corners=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],float)
    size=tuple((np.ceil((corners@m[:,:2].T+m[:,2]).max(axis=0))+1).astype(int))
    rotated=cv2.warpAffine(template,m,size,flags=cv2.INTER_LINEAR)
    mask=cv2.warpAffine(np.ones(template.shape,np.uint8),m,size,flags=cv2.INTER_NEAREST)
    scores=cv2.matchTemplate(signal,rotated,cv2.TM_CCOEFF_NORMED,mask=mask)
    scores=np.where(np.isfinite(scores),scores,-1.)
    score=float(scores[location[1],location[0]])
    other=scores.copy();cx,cy=location
    other[max(0,cy-15):cy+16,max(0,cx-15):cx+16]=-1
    margin=score-float(other.max())
    h=np.eye(3);h[:2,:2]=m[:,:2]
    h[:2,2]=m[:,2]+np.array(location)-m[:,:2]@low
    center=tracker.anchor.corners.mean(axis=0)
    displacement=h[:2,:2]@center+h[:2,2]-center
    info=dict(method='whole_plate_rotation_template',score=float(score),margin=float(margin),
        unmasked_score=float(raw_score),angle_deg=float(angle),scale=float(scale),
        displacement_px=float(np.linalg.norm(displacement)),accepted_pose=False)
    if (not np.isfinite(h).all() or not np.isfinite([score,margin]).all()
            or score<.65 or margin<.03 or np.linalg.norm(displacement)>150):
        return None,dict(info,initializer_rejected=True)
    return h,info
