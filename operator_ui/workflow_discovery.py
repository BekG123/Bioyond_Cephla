"""Discover the installed tool schemas, not a second hand-maintained workflow list."""
from copy import deepcopy

from researcher_teaching import TeachingError


def discover(agent=None, workflow=None, *, tools=None):
    if tools is None:
        from lacry_agent import TOOLS
        tools = list(TOOLS)
        if agent is not None:
            tools += agent.lab_api.tools()
    by_name = {tool['name']: tool for tool in tools}
    if workflow is not None:
        if workflow not in by_name:
            raise TeachingError('Unknown installed workflow/tool: '+workflow)
        return deepcopy(by_name[workflow])
    return [dict(name=name, description=tool['description'],
                 required_inputs=tool.get('input_schema',{}).get('required',[]),
                 input_names=list(tool.get('input_schema',{}).get('properties',{})),
                 schema_lookup=dict(tool='get_workflow_catalog',arguments=dict(workflow=name)))
            for name,tool in sorted(by_name.items())]
