"""Offline edge-profile measurements; not connected to robot commands."""
import cv2
import numpy as np
from vision import DetectionError

def rim_edges(image,corners,polarities=None,half_width=14.):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    gray=cv2.GaussianBlur(gray.astype(np.float32),(5,5),1.)
    q=np.asarray(corners,float);lines=[];evidence=[]
    for side in range(4):
        a,b=q[side],q[(side+1)%4];v=b-a;length=np.linalg.norm(v);v/=length
        normal=np.array([-v[1],v[0]])
        fractions=np.linspace(.12,.88,160);offsets=np.arange(-half_width,half_width+.01,.25)
        bases=a+fractions[:,None]*(b-a)
        samples=bases[:,None,:]+offsets[None,:,None]*normal
        values=cv2.remap(gray,samples[:,:,0].astype(np.float32),samples[:,:,1].astype(np.float32),cv2.INTER_LINEAR)
        gradient=np.gradient(values,.25,axis=1)
        # Retain several local edge candidates: the strongest response alone
        # switches between the flange, shadows and specular highlights.
        magnitude=abs(gradient)
        peaks=np.full((len(fractions),4),-1,int)
        for row in range(len(fractions)):
            candidates=np.where((magnitude[row,1:-1]>=magnitude[row,:-2])&(magnitude[row,1:-1]>magnitude[row,2:]))[0]+1
            selected=[]
            for index in sorted(candidates,key=lambda i:-magnitude[row,i]):
                if index<3 or index>=len(offsets)-3 or magnitude[row,index]<2:continue
                if polarities is not None and np.sign(gradient[row,index])!=polarities[side]:continue
                if all(abs(index-j)>=8 for j in selected):selected.append(index)
                if len(selected)==4:break
            peaks[row,:len(selected)]=selected
        candidate_offsets=np.where(peaks>=0,offsets[np.maximum(peaks,0)],np.nan)
        # A real straight edge must have support distributed along its length.
        best=None;best_score=None;best_indices=None
        rng=np.random.default_rng(0)
        for _ in range(1000):
            ids=np.flatnonzero(np.isfinite(candidate_offsets).any(axis=1))
            if len(ids)<50:break
            i,j=rng.choice(ids,2,replace=False)
            if abs(fractions[i]-fractions[j])<.2:continue
            di=rng.choice(candidate_offsets[i,np.isfinite(candidate_offsets[i])]);dj=rng.choice(candidate_offsets[j,np.isfinite(candidate_offsets[j])])
            slope=(dj-di)/(fractions[j]-fractions[i]);intercept=di-slope*fractions[i]
            if abs(slope)>6:continue
            residual=abs(candidate_offsets-(slope*fractions[:,None]+intercept))
            residual=np.nan_to_num(residual,nan=1e6)
            index=np.argmin(residual,axis=1);error=residual[np.arange(len(fractions)),index]
            inside=error<1.
            score=(int(inside.sum()),-float(np.mean(error[inside])) if inside.any() else -1e6)
            if best_score is None or score>best_score:best=inside;best_score=score;best_indices=index
        if best is None or best.sum()<.65*len(fractions):
            raise DetectionError(f'Edge {side}: only {0 if best is None else best.sum()}/160 consistent profiles.')
        if min(np.histogram(fractions[best],bins=np.linspace(.12,.88001,5))[0])<15:
            raise DetectionError(f'Edge {side}: insufficient distributed support.')
        peak=peaks[np.arange(len(fractions)),best_indices]
        displacement=candidate_offsets[np.arange(len(fractions)),best_indices]
        strength=magnitude[np.arange(len(fractions)),np.maximum(peak,0)]
        polarity=np.sign(gradient[np.arange(len(fractions)),np.maximum(peak,0)])
        slope,intercept=np.polyfit(fractions[best],displacement[best],1)
        residual=displacement[best]-(slope*fractions[best]+intercept)
        rms=float(np.sqrt(np.mean(residual**2)))
        if rms>.6:raise DetectionError(f'Edge {side}: residual {rms:.3f} px.')
        p0=a+intercept*normal;p1=b+(slope+intercept)*normal
        line=np.cross([*p0,1.],[*p1,1.]);line/=np.linalg.norm(line[:2]);lines.append(line)
        evidence.append(dict(side=side,inliers=int(best.sum()),samples=160,rms_px=rms,
            normal_offset_px=float(intercept),slope_px=float(slope),median_strength=float(np.median(strength[best])),
            polarity=float(np.median(polarity[best])),points=(bases[best]+displacement[best,None]*normal).tolist()))
    fitted=[]
    for i in range(4):
        point=np.cross(lines[i-1],lines[i])
        if abs(point[2])<1e-6:raise DetectionError('Parallel adjacent rim edges.')
        fitted.append(point[:2]/point[2])
    fitted=np.float32(fitted)
    if not cv2.isContourConvex(fitted):raise DetectionError('Nonconvex fitted rim.')
    return fitted,evidence
