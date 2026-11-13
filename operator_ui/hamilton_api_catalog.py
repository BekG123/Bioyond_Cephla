"""Pinned NimbusLite API discovery and request validation; no network or motion."""
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import quote, urlencode

from hamilton_prep import digest
from researcher_teaching import TeachingError

SCHEMA_PATH=Path(__file__).parent/'contracts/hamilton_openapi.json'
METHODS=('get','post','put','patch','delete')
# Authentication material and human signatures never travel through model tools.
PRIVATE_GROUPS={'authenticate','credentials','user-kba','users','backups'}
PRIVATE_PATHS={'/api/v1/verification/authenticate','/api/v1/verification/signature',
    '/api/v1/verification/signature/clear'}
MUTATING_GET={'/api/v1/protocols/validate/{protocolId}',
    '/api/v1/users/disable-user-management','/api/v1/protocol-verification/{id}'}
LIFECYCLE_GROUPS={'protocol-run','calibration','maintenance','verification','diagnostics',
    'instruments','power','thermal-device','hepa-uv','repair','service-software-api'}
READ_GROUPS={'calibration','camera','deck','diagnostics','enclosure','environment','errors',
    'hepa-uv','instruments','labware','labware-categories','labware-signature','lighting',
    'liquid-classes','maintenance','power','protocol-run','protocols','protocol-support',
    'protocol-verification','report','roles','run-data','screenshots','service-software-api',
    'software-versions','system-ready','system-time','thermal-device','traces',
    'verification','verification-result'}


def normalized_schema(value):
    """OpenAPI 3.0 nullable -> JSON Schema without removing constraints."""
    if isinstance(value,list):return [normalized_schema(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:normalized_schema(v) for k,v in value.items() if k!='nullable'}
    if value.get('nullable'):result={'anyOf':[result,{'type':'null'}]}
    return result


class HamiltonCatalog:
    def __init__(self,path=SCHEMA_PATH):
        self.document=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        self.hash=digest(self.document)
        self.operations={method.upper()+' '+path:(path,method,op)
            for path,entry in self.document['paths'].items()
            for method,op in entry.items() if method in METHODS}

    def operation(self,key):
        if key not in self.operations:raise TeachingError('Choose an exact operation key from get_hamilton_api_catalog.',400)
        return self.operations[key]

    def policy(self,key):
        path,method,op=self.operation(key);group=path.split('/')[3]
        content=op.get('requestBody',{}).get('content',{})
        if (group in PRIVATE_GROUPS or path in PRIVATE_PATHS or
                (method!='get' and (group=='verification-result' or path=='/api/v1/calibration/channel-results'))):return 'operator_only'
        if content and not any('json' in media for media in content):return 'file_upload_adapter_required'
        if method=='get' and group in READ_GROUPS and path not in MUTATING_GET:return 'read'
        if path in ('/api/v1/protocol-run/create','/api/v1/protocol-run/load-complete'):
            return 'reviewed_protocol_workflow'
        return 'human_confirmed_request'

    def search(self,query='',offset=0,limit=25):
        if not isinstance(query,str) or len(query)>200 or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:
            raise TeachingError('Use a search string, nonnegative offset and limit 1–50.',400)
        matches=[]
        for key,(path,method,op) in self.operations.items():
            if all(word in (key+' '+op.get('summary','')).lower() for word in query.lower().split()):
                matches.append(dict(operation=key,summary=op.get('summary',''),access=self.policy(key)))
        return dict(schema_hash=self.hash,total_operations=len(self.operations),matched=len(matches),
            operations=matches[offset:offset+limit],next_offset=offset+limit if offset+limit<len(matches) else None)

    def detail(self,key):
        path,method,op=self.operation(key)
        refs={}
        def collect(value):
            if isinstance(value,dict):
                ref=value.get('$ref')
                if ref and ref not in refs:
                    if not ref.startswith('#/components/schemas/'):raise TeachingError('External schema reference is not allowed.')
                    refs[ref]=deepcopy(self.document['components']['schemas'][ref.rsplit('/',1)[-1]])
                    collect(refs[ref])
                for v in value.values():collect(v)
            elif isinstance(value,list):
                for v in value:collect(v)
        collect(op)
        return dict(operation=key,access=self.policy(key),schema_hash=self.hash,definition=deepcopy(op),schemas=refs)

    def validate(self,value,schema):
        from jsonschema import Draft4Validator
        root=normalized_schema(dict(schema,components=self.document['components']))
        errors=list(Draft4Validator(root).iter_errors(value))
        if errors:
            error=errors[0]
            # Do not echo potentially sensitive input values in model-visible errors.
            raise TeachingError('API input fails schema at '+('/'.join(map(str,error.absolute_path)) or 'root')+' ('+str(error.validator)+').',400)

    def request(self,operation,path_parameters=None,query=None,body=None):
        path,method,op=self.operation(operation)
        values={'path':path_parameters or {},'query':query or {}}
        if any(not isinstance(v,dict) for v in values.values()):raise TeachingError('Parameters must be objects.',400)
        parameters=self.document['paths'][path].get('parameters',[])+op.get('parameters',[])
        params={(p['in'],p['name']):p for p in parameters}
        for location,mapping in values.items():
            if set(mapping)-{name for place,name in params if place==location}:raise TeachingError('Unknown API parameter.',400)
        rendered=path
        query_pairs=[]
        for (location,name),parameter in params.items():
            if location not in values:raise TeachingError('This operation needs a nonstandard parameter adapter.')
            mapping=values[location]
            if name not in mapping:
                if parameter.get('required'):raise TeachingError('Missing API parameter '+name+'.',400)
                continue
            value=mapping[name];self.validate(value,parameter.get('schema',{}))
            def scalar(v):
                if isinstance(v,(dict,list)) or v is None:raise TeachingError('Unsupported parameter encoding.',400)
                return str(v).lower() if isinstance(v,bool) else str(v)
            if location=='path':
                text=scalar(value)
                if not text or any(x in text for x in ('/','\\','..','%','?','#')) or any(ord(c)<32 for c in text):
                    raise TeachingError('Invalid API path parameter.',400)
                rendered=rendered.replace('{'+name+'}',quote(text,safe=''))
            else:
                items=value if isinstance(value,list) else [value]
                if parameter.get('explode',True):query_pairs.extend((name,scalar(v)) for v in items)
                else:query_pairs.append((name,','.join(scalar(v) for v in items)))
        request=op.get('requestBody',{});content=request.get('content',{})
        schema=next((v.get('schema',{}) for k,v in content.items() if 'json' in k),None)
        if body is not None:
            if schema is None:raise TeachingError('This endpoint has no JSON request body.',400)
            self.validate(body,schema)
        elif request.get('required'):raise TeachingError('This endpoint requires a request body.',400)
        json.dumps(body,allow_nan=False)
        if len(json.dumps(body))>1000000:raise TeachingError('API body exceeds 1 MB.',400)
        if re.search(r'{[^}]*}',rendered):raise TeachingError('Unresolved path parameter.',400)
        return dict(method=method.upper(),path=rendered.removeprefix('/api/v1/')+('?' + urlencode(query_pairs) if query_pairs else ''),body=deepcopy(body))

    def needs_completion_review(self,key):
        path,method,op=self.operation(key)
        # Unknown effects are never assumed synchronous physical completion.
        return path.split('/')[3] not in {'protocols','labware','liquid-classes','labware-signature'} and not (
            path=='/api/v1/deck/{protocolId}')
