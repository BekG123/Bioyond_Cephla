exec((__import__('pathlib').Path(__file__).with_name('probe_rim_search.py')).read_text().split('for ident in')[0])
for ident in ['a04cc11d024b4461b295820402b30245','9b9c05b4a29b4a818b5cb44f763fc601','7c29ef6a68724ffeb9a4365456a98e33']:
    image=cv2.resize(cv2.imread(str(ROOT/'operator_ui/reports/plate_session/cellvis24_workflows'/ident/'prepared_median_0.png')),(1200,800))
    for lo in [.18,.2,.22,.25]:
        m=types.ModuleType('probe');exec(source.replace('np.linspace(.12,.88,160)',f'np.linspace({lo},{1-lo},160)').replace('np.linspace(.12,.88001,5)',f'np.linspace({lo},{1-lo+.00001},5)'),m.__dict__)
        try:
            corners,edges=m.rim_edges(image,seed,[-1]*4)
            result=dict(corners=corners.tolist(),edges=[{k:e[k] for k in ['inliers','rms_px','slope_px','normal_offset_px']} for e in edges])
        except Exception as e:result=dict(error=str(e))
        print(json.dumps(dict(id=ident,span=[lo,1-lo],**result)),flush=True)
