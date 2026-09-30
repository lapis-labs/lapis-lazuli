<!-- lapis-lazuli 0.1.1, from dist/AGENTS.snippet.md -->
## LapisLazuli design skills

- At the start of a design task, run `lazuli local fonts --summary` and read the local font inventory summary it prints before choosing fonts.
- MCP server `lapis-lazuli`: run `lapis-design mcp` over stdio. Register it in this harness's own MCP settings, for example `{"mcpServers": {"lapis-lazuli": {"command": "lapis-design", "args": ["mcp"]}}}`.
- Both commands come with the lapis-design CLI; `lazuli doctor` checks the install.
