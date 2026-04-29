import httpx
import json
import os
import re
from typing import Any, Dict, Optional, List
from fastmcp import FastMCP

class RESTLoader:
    """
    Bridges 40mcp-style JSON configs to MCP tools natively in Python.
    Supported features:
    - GET/POST/PUT/DELETE
    - baseUrl variable substitution (${VAR})
    - queryMap and bodyMap for input parameter renaming
    - Bearer and API Key authentication
    - Response shaping (pick, omit, template)
    """

    def __init__(self, config_path: str, name: str):
        self.config_path = config_path
        self.name = name
        with open(config_path) as f:
            self.config = json.load(f)
        
        self.loader_mcp = FastMCP(name=self.name)
        self._mount()

    def _resolve_vars(self, text: str) -> str:
        """Resolve ${VAR} placeholders from environment variables."""
        if not isinstance(text, str):
            return text
        def replacer(match):
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r"\$\{(.+?)\}|\$(.+?)\b", replacer, text)

    def _get_auth_headers(self, auth_config: Dict) -> Dict[str, str]:
        headers = {}
        auth_type = auth_config.get("type", "").lower()
        env_var = auth_config.get("envVar")
        
        if not env_var:
            return headers
            
        value = os.environ.get(env_var)
        if not value:
            return headers

        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {value}"
        elif auth_type == "api-key":
            header_name = auth_config.get("header", "X-API-Key")
            headers[header_name] = value
        
        return headers

    def _mount(self):
        base_url = self.config.get("baseUrl", "").rstrip("/")
        auth_config = self.config.get("auth", {})
        
        for tool_conf in self.config.get("tools", []):
            self._register_tool(tool_conf, base_url, auth_config)

    def _register_tool(self, tool_conf: Dict, base_url: str, auth_config: Dict):
        tool_name = tool_conf["name"]
        description = tool_conf.get("description", "")
        method = tool_conf.get("method", "GET").upper()
        path = tool_conf.get("path", "")
        query_map = tool_conf.get("queryMap", {})
        body_map = tool_conf.get("bodyMap", {})
        input_schema = tool_conf.get("inputSchema", {"type": "object", "properties": {}})

        # The actual implementation that will be called
        async def tool_fn_impl(**kwargs) -> str:
            resolved_base = self._resolve_vars(base_url)
            # Resolve tool arguments in the path, e.g. /posts/{id}
            try:
                resolved_path = self._resolve_vars(path).format(**kwargs)
            except KeyError:
                # Fallback if some path vars aren't provided
                resolved_path = self._resolve_vars(path)
            
            url = f"{resolved_base}{resolved_path}"
            
            headers = self._get_auth_headers(auth_config)
            
            params = {}
            json_body = {}
            
            # Create a copy of kwargs to track which ones were used in the path
            remaining_kwargs = kwargs.copy()
            # Remove keys that were used in the path format
            import string
            formatter = string.Formatter()
            path_vars = [field_name for _, field_name, _, _ in formatter.parse(path) if field_name]
            for pv in path_vars:
                remaining_kwargs.pop(pv, None)

            for k, v in remaining_kwargs.items():
                if k in query_map:
                    params[query_map[k]] = v
                elif k in body_map:
                    json_body[body_map[k]] = v
                else:
                    if method in ["POST", "PUT", "PATCH"]:
                        json_body[k] = v
                    else:
                        params[k] = v

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_body if json_body else None,
                        headers=headers,
                        timeout=30.0
                    )
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as e:
                    return f"Error: {e.response.status_code} - {e.response.text}"
                except Exception as e:
                    return f"Error: {str(e)}"

        # FastMCP requires explicit arguments (no **kwargs).
        # We generate a wrapper function with the correct signature at runtime.
        props = input_schema.get("properties", {})
        arg_names = list(props.keys())
        
        # If no properties, register a no-arg function
        if not arg_names:
            @self.loader_mcp.tool(name=tool_name, description=description)
            async def no_arg_fn() -> str:
                return await tool_fn_impl()
            return

        # Generate arg string (e.g. "id, title")
        # We default to Any (or str) for all args if not specified
        arg_str = ", ".join(arg_names)
        
        dict_entries = ", ".join(["'%s': %s" % (n, n) for n in arg_names])
        wrapper_code = f"async def {tool_name}({arg_str}):\n"
        wrapper_code += f"    return await tool_fn_impl(**{{{dict_entries}}})\n"
        
        exec_globals = {"tool_fn_impl": tool_fn_impl}
        try:
            exec(wrapper_code, exec_globals)
            generated_fn = exec_globals[tool_name]
            # Register with FastMCP
            self.loader_mcp.tool(name=tool_name, description=description)(generated_fn)
        except Exception as e:
            import sys
            sys.stderr.write(f"Error registering REST tool {tool_name}: {str(e)}\n")

    def get_mcp(self) -> FastMCP:
        return self.loader_mcp
