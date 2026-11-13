"""Offline edge-profile measurements; not connected to robot commands."""
import cv2
import numpy as np
from vision import DetectionError

def robust_profile_line(fractions,candidates,inside,indices):
    """Smooth robust least squares, seeded by the measured RANSAC consensus.

    Geman-McClure weights (1.5 px scale) avoid abrupt changes in the final
    line when a peak crosses the 1 px membership boundary. Membership and
    all acceptance gates are recomputed afterward; weights do not add support.
    """
    rows=np.arange(len(fractions));a=np.column_stack([fractions,np.ones(len(fractions))])
    coef=np.polyfit(fractions[inside],candidates[rows,indices][inside],1)
    converged=False
    for _ in range(60):
        error=np.nan_to_num(abs(candidates-a.dot(coef)[:,None]),nan=1e6)
        indices=np.argmin(error,axis=1);y=candidates[rows,indices];valid=np.isfinite(y)
        residual=error[rows,indices];weights=1/(1+(residual/1.5)**2)**2
        weights[~valid]=0
        if valid.sum()<2:raise DetectionError('Insufficient measured peaks for robust rim fit.')
        next_coef,_,rank,_=np.linalg.lstsq(a[valid]*np.sqrt(weights[valid,None]),y[valid]*np.sqrt(weights[valid]),rcond=None)
        if rank<2 or not np.isfinite(next_coef).all():raise DetectionError('Invalid robust rim fit.')
        if np.max(abs(a.dot(next_coef-coef)))<1e-5:
            coef=next_coef;converged=True;break
        coef=next_coef
    if not converged:raise DetectionError('Robust rim fit did not converge.')
    error=np.nan_to_num(abs(candidates-a.dot(coef)[:,None]),nan=1e6)
    indices=np.argmin(error,axis=1);inside=error[rows,indices]<1.
    return coef,inside,indices

def refine_consensus(fractions,candidates,inside,indices,max_iterations=10):
    """Locally refit a rejected RANSAC hypothesis; never relax its gates.

    A two-profile hypothesis can miss support present around its least-squares
    line. Reassign the nearest measured peak after each fit, requiring stable
    membership before returning it. Nonconvergence retains the original result.
    """
    original=(inside,indices)
    rows=np.arange(len(fractions))
    for _ in range(max_iterations):
        if inside is None or inside.sum()<2:return original
        slope,intercept=np.polyfit(fractions[inside],candidates[rows,indices][inside],1)
        if not np.isfinite([slope,intercept]).all() or abs(slope)>6:return original
        errors=np.nan_to_num(abs(candidates-(slope*fractions[:,None]+intercept)),nan=1e6)
        updated_indices=np.argmin(errors,axis=1)
        updated_inside=errors[rows,updated_indices]<1.
        if np.array_equal(updated_inside,inside) and np.array_equal(updated_indices[inside],indices[inside]):
            return inside,indices
        inside,indices=updated_inside,updated_indices
    return original

def rim_edges(image,corners,polarities=None,half_width=14.,sample_span=(.12,.88),tangent_radius=0):
    # A profile may exclude known rounded ends / fixture tabs. Never select
    # a smaller span dynamically just to make a failed image pass.
    lo,hi=sample_span
    if not np.isfinite([lo,hi]).all() or not 0<=lo<hi<=1 or hi-lo<.5-1e-9:
        raise ValueError('Rim sampling must cover at least 50% of each side.')
    if type(tangent_radius) is not int or not 0<=tangent_radius<=2:
        raise ValueError('Rim tangent averaging radius must be 0..2 pixels.')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    gray=cv2.GaussianBlur(gray.astype(np.float32),(5,5),1.)
    q=np.asarray(corners,float);lines=[];evidence=[]
    for side in range(4):
        a,b=q[side],q[(side+1)%4];v=b-a;length=np.linalg.norm(v);v/=length
        normal=np.array([-v[1],v[0]])
        fractions=np.linspace(lo,hi,160);offsets=np.arange(-half_width,half_width+.01,.25)
        bases=a+fractions[:,None]*(b-a)
        samples=bases[:,None,:]+offsets[None,:,None]*normal
        # Average along the rim, not across it, to reduce dark-pixel noise
        # without broadening the measured edge's normal profile.
        values=np.mean([cv2.remap(gray,(samples[:,:,0]+t*v[0]).astype(np.float32),
                      (samples[:,:,1]+t*v[1]).astype(np.float32),cv2.INTER_LINEAR)
                      for t in range(-tangent_radius,tangent_radius+1)],axis=0)
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
        initial_inliers=0 if best is None else int(best.sum())
        # Preserve successful legacy fits. The separately re-referenced
        # central-rim profile always refines to stable peak membership.
        if best is not None and (best.sum()<.65*len(fractions) or tuple(sample_span)!=(.12,.88)):
            best,best_indices=refine_consensus(fractions,candidate_offsets,best,best_indices)
        robust_coef=None
        if best is not None and best.sum()>=.65*len(fractions) and tuple(sample_span)!=(.12,.88):
            robust_coef,best,best_indices=robust_profile_line(fractions,candidate_offsets,best,best_indices)
        if best is None or best.sum()<.65*len(fractions):
            raise DetectionError(f'Edge {side}: only {0 if best is None else best.sum()}/160 consistent profiles.')
        support_bins=np.histogram(fractions[best],bins=np.linspace(lo,hi+.00001,5))[0]
        if min(support_bins)<15:
            raise DetectionError(f'Edge {side}: insufficient distributed support.')
        peak=peaks[np.arange(len(fractions)),best_indices]
        displacement=candidate_offsets[np.arange(len(fractions)),best_indices]
        strength=magnitude[np.arange(len(fractions)),np.maximum(peak,0)]
        polarity=np.sign(gradient[np.arange(len(fractions)),np.maximum(peak,0)])
        slope,intercept=np.polyfit(fractions[best],displacement[best],1) if robust_coef is None else robust_coef
        residual=displacement[best]-(slope*fractions[best]+intercept)
        rms=float(np.sqrt(np.mean(residual**2)))
        if rms>.6:raise DetectionError(f'Edge {side}: residual {rms:.3f} px.')
        p0=a+intercept*normal;p1=b+(slope+intercept)*normal
        line=np.cross([*p0,1.],[*p1,1.]);line/=np.linalg.norm(line[:2]);lines.append(line)
        evidence.append(dict(side=side,inliers=int(best.sum()),samples=160,rms_px=rms,
            initial_inliers=initial_inliers,consensus_refined=initial_inliers<.65*len(fractions) or tuple(sample_span)!=(.12,.88),
            sample_span=[lo,hi],tangent_radius=tangent_radius,support_bins=support_bins.tolist(),
            line_fit='legacy-ls' if robust_coef is None else 'gm-irls-1.5px-v1',
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
