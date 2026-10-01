import argparse
import sys
import json
from automation.mcp.server import mcp

def main():
    parser = argparse.ArgumentParser(description="AURA MCP Server")
    parser.add_argument("--transport", type=str, choices=["stdio", "http"], default="stdio",
                        help="The transport mechanism to use (default: stdio)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port to run the HTTP server on (default: 8000)")
    parser.add_argument("--list-tools", action="store_true",
                        help="List all available tools and exit")
    parser.add_argument("--generate-configs", action="store_true",
                        help="Generate client configs and exit")
    
    args = parser.parse_args()

    if args.list_tools:
        print("Available Tools:")
        print(" - aura_list_agents")
        print(" - aura_get_agent_info")
        print(" - aura_execute_action")
        print(" - aura_list_windows")
        sys.exit(0)
        
    if args.generate_configs:
        config = {
            "mcpServers": {
                "aura": {
                    "command": sys.executable,
                    "args": ["-m", "automation.mcp"],
                    "cwd": ".",
                    "disabled": False,
                    "autoApprove": [
                        "aura_list_agents",
                        "aura_get_agent_info",
                        "aura_list_windows"
                    ]
                }
            }
        }
        print("Claude Desktop / Cursor Config:")
        print(json.dumps(config, indent=2))
        sys.exit(0)

    if args.transport == "stdio":
        print("Starting AURA MCP Server on stdio...", file=sys.stderr)
        mcp.run()
    elif args.transport == "http":
        print(f"Starting AURA MCP Server on HTTP/SSE port {args.port}...", file=sys.stderr)
        # MCPServer uses sse transport
        mcp.run(transport="sse")
