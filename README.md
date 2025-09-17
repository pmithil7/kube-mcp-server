# kube-mcp-server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![MCP](https://img.shields.io/badge/MCP-1.12+-purple.svg)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://hub.docker.com/r/pmithil7/kube-mcp-server)

A **production-ready FastAPI-based Model Context Protocol (MCP) server** that enables AI assistants like Claude, Cursor, and GitHub Copilot to manage Kubernetes clusters through natural language. Features multi-context support, security controls, and comprehensive cluster diagnostics.

## 🚀 Features

- **🔐 Security-First Design**: Built-in destructive command blocklist prevents dangerous operations
- **🌐 Multi-Context Support**: Seamlessly switch between different Kubernetes clusters and contexts
- **🔍 Advanced Diagnostics**: Intelligent pod failure detection and comprehensive troubleshooting
- **📊 Node Health Monitoring**: Memory usage tracking and node health assessment
- **⚡ FastAPI Backend**: High-performance async API with automatic OpenAPI documentation
- **🤖 MCP Compatible**: Full Model Context Protocol support for AI assistant integration
- **🐳 Container Ready**: Production Docker image with security best practices
- **📋 Flexible Configuration**: Environment variables, INI files, and CLI options
- **🛡️ Safe Operations**: Comprehensive input validation

## 📋 Prerequisites

- Python 3.8+
- `kubectl` installed and configured
- Access to a Kubernetes cluster
- Valid kubeconfig file

## 🛠️ Installation

### Option 1: Docker (Recommended)

```bash
# Pull the latest image
docker pull pmithil7/kube-mcp-server:latest

# Run with your kubeconfig mounted
docker run -p 8000:8000 \
  -v ~/.kube/config:/root/.kube/config:ro \
  pmithil7/kube-mcp-server:latest
```

### Option 2: From Source

```bash
git clone https://github.com/pmithil7/kube-mcp-server.git
cd kube-mcp-server
pip install -r requirements.txt
python kubectl_mcp-server.py
```

### Option 3: pip install (Coming Soon)

```bash
pip install kube-mcp-server
```

## 🚦 Quick Start

### 1. Start the MCP Server

```bash
# Basic start (uses default kubeconfig)
python kubectl_mcp-server.py

# With custom port
uvicorn kubectl_mcp-server:app --host 0.0.0.0 --port 8000

# Docker with custom kubeconfig path
docker run -p 8000:8000 -v /path/to/kubeconfig:/root/.kube/config pmithil7/kube-mcp-server
```

### 2. Configure with Claude Desktop

Add to your Claude Desktop config (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kube-mcp-server": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/Users/yourname/.kube/config:/root/.kube/config:ro",
        "-p", "8000:8000",
        "pmithil7/kube-mcp-server:latest"
      ]
    }
  }
}
```

### 3. Start Managing Your Cluster with AI

Ask Claude natural language questions like:
- "Show me all failing pods across all namespaces"
- "What's wrong with my frontend deployment in production?"
- "Find nodes with high memory usage above 80%"
- "Troubleshoot the nginx pod in default namespace"
- "Restart the api-gateway deployment"
- "Switch to the staging cluster context"

## 🔧 Configuration

### Environment Variables

```bash
# Kubeconfig location
export KUBECONFIG=/path/to/your/kubeconfig

# Temp directory for processing
export MCP_TEMP_DIR=/tmp/kube-mcp

# Slack integration (optional)
export SLACK_USER_ID=your-slack-user-id
```

### Vault Integration (Enterprise)

For secure kubeconfig management, place your kubeconfig in an INI format at:
```
/vault/secrets/kubectl.ini
```

The server will automatically detect and use this configuration.

### Security Controls

The server includes a built-in blocklist for destructive operations:
- `delete`, `drain`, `cordon`, `uncordon`
- `label`, `annotate`, `taint`
- `apply`, `patch`, `replace`, `edit`, `set`

To modify the blocklist, edit the `DESTRUCTIVE_COMMAND_BLOCKLIST` in the source code.

## 📚 API Endpoints

### Core Operations
- `POST /mcp/get_pods` - List all pods in a namespace
- `POST /mcp/get_failing_pods` - Find problematic pods with intelligent failure detection
- `POST /mcp/describe_pod` - Get detailed pod information
- `POST /mcp/get_pod_logs` - Retrieve pod logs (last 50 lines)
- `POST /mcp/troubleshoot_pod` - Comprehensive pod diagnostics

### Deployment Management  
- `POST /mcp/get_deployments` - List deployments
- `POST /mcp/restart_deployment` - Rolling restart of deployments

### Cluster Health
- `POST /mcp/get_unhealthy_nodes` - Find nodes not in Ready state
- `POST /mcp/get_nodes_by_memory` - Identify high memory usage nodes

### Advanced Operations
- `POST /mcp/execute_kubectl` - Execute custom kubectl commands (with safety controls)

### Request Format

All endpoints expect a JSON body with this structure:

```json
{
  "entities": {
    "namespace": "default",
    "pod_name": "nginx-pod",
    "deployment_name": "api-server", 
    "kube_context": "production-cluster",
    "memory_threshold_percent": 80,
    "command": "get services",
    "args": ["-o", "wide"]
  }
}
```

## 🔒 Security Considerations

- **RBAC**: Ensure your kubeconfig has appropriate permissions
- **Network Security**: Run on localhost by default
- **Authentication**: Inherits kubectl authentication

## 🐳 Docker Usage

```bash
# Run with mounted kubeconfig
docker run -p 8000:8000 -v ~/.kube/config:/root/.kube/config pmithil7/kube-mcp-server

```

## 🔌 Integration Examples

### With Claude Desktop

```json
{
  "mcpServers": {
    "kubernetes": {
      "command": "kube-mcp-server",
      "args": ["--port", "8000"],
      "env": {
        "KUBECONFIG": "/path/to/your/kubeconfig"
      }
    }
  }
}
```

### With Cursor IDE

Install as MCP server and configure in Cursor settings.

### Programmatic Usage

```python
from kube_mcp_server import KubeMCPServer

server = KubeMCPServer(
    kubeconfig_path="/path/to/kubeconfig",
    read_only=True
)
server.start()
```

## 🧪 Development

### Setup Development Environment

```bash
git clone https://github.com/pmithil7/kube-mcp-server.git
cd kube-mcp-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt
pip install -e .

# Run tests
pytest

# Run linting
black .
flake8 .
mypy .
```

### Project Structure

```
kube-mcp-server/
├── src/
│   └── kube_mcp_server/
│       ├── __init__.py
│       ├── main.py
│       ├── server.py
│       ├── handlers/
│       └── utils/
├── tests/
├── docs/
├── docker/
├── requirements.txt
├── requirements-dev.txt
├── setup.py
├── pyproject.toml
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
└── LICENSE
```

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests for new functionality
5. Run the test suite (`pytest`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## 📖 Documentation

- [API Documentation](docs/api.md)
- [Configuration Guide](docs/configuration.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Examples](docs/examples/)

## 🐛 Troubleshooting

### Common Issues

**Connection Refused**
```bash
# Check if kubectl works
kubectl cluster-info

# Verify kubeconfig
kubectl config current-context
```

**Permission Denied**
```bash
# Check RBAC permissions
kubectl auth can-i get pods
kubectl auth can-i create deployments
```

**Server Won't Start**
```bash
# Check port availability
lsof -i :8000

# Enable debug logging
kube-mcp-server --log-level DEBUG
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) specification
- [FastAPI](https://fastapi.tiangolo.com/) framework
- [Kubernetes](https://kubernetes.io/) community
- All contributors and maintainers

## 📊 Project Status

![GitHub stars](https://img.shields.io/github/stars/pmithil7/kube-mcp-server)
![GitHub issues](https://img.shields.io/github/issues/pmithil7/kube-mcp-server)
![GitHub pull requests](https://img.shields.io/github/issues-pr/pmithil7/kube-mcp-server)

---

**Made with ❤️ by [pmithil7](https://github.com/pmithil7)**

For questions or support, please [open an issue](https://github.com/pmithil7/kube-mcp-server/issues) or join our [discussions](https://github.com/pmithil7/kube-mcp-server/discussions).
