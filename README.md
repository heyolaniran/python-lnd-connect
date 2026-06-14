# LND Lightning API Server

A Python FastAPI server that provides an open HTTP API for interacting with up to **3 LND Lightning Network nodes**. This API allows you to perform common Lightning Network operations without HTTP authentication.

## Features

- **No Authentication Required** - Open API for easy integration (see security note below)
- **Multi-Node Support** - Connect to up to 3 LND nodes (ideal for Polar regtest networks)
- **Lightning Operations** - Create invoices, send payments, check balances
- **Channel Liquidity** - Per-channel inbound/outbound liquidity and pending channel state
- **Node Information** - Get node status, channel info, and network data
- **Payment History** - View invoices and payment records
- **Developer Friendly** - Auto-generated OpenAPI documentation
- **Virtual Environment** - Isolated Python environment for clean dependencies

## API Endpoints

Routes without a node prefix target **node 1** for backward compatibility. Use `/nodes/{node_id}/...` to target a specific node (`1`, `2`, or `3`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API information |
| GET | `/nodes` | List configured nodes and connection status |
| GET | `/health` | Health check for node 1 |
| GET | `/nodes/{node_id}/health` | Health check for a specific node |
| GET | `/info` | Detailed node information (node 1) |
| GET | `/nodes/{node_id}/info` | Detailed node information |
| GET | `/balance` | Wallet and channel balances (node 1) |
| GET | `/nodes/{node_id}/balance` | Wallet and channel balances |
| GET | `/channels` | Open channels, liquidity summary, pending channels (node 1) |
| GET | `/nodes/{node_id}/channels` | Open channels, liquidity summary, pending channels |
| POST | `/invoices` | Create a new invoice (node 1) |
| POST | `/nodes/{node_id}/invoices` | Create a new invoice |
| GET | `/invoices` | List all invoices (node 1) |
| GET | `/nodes/{node_id}/invoices` | List all invoices |
| GET | `/invoices/{r_hash}` | Get specific invoice (node 1) |
| GET | `/nodes/{node_id}/invoices/{r_hash}` | Get specific invoice |
| POST | `/payments` | Send a payment (node 1) |
| POST | `/nodes/{node_id}/payments` | Send a payment |
| GET | `/payments` | List payment history (node 1) |
| GET | `/nodes/{node_id}/payments` | List payment history |
| GET | `/decode/{payment_request}` | Decode payment request (node 1) |
| GET | `/nodes/{node_id}/decode/{payment_request}` | Decode payment request |
| POST | `/signmessage` | Sign a message with the node's private key (node 1) |
| POST | `/nodes/{node_id}/signmessage` | Sign a message |
| POST | `/verifymessage` | Verify a signed message (node 1) |
| POST | `/nodes/{node_id}/verifymessage` | Verify a signed message |

### Channels query parameters

`GET /nodes/{node_id}/channels` supports:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `active_only` | `false` | Return only active channels |
| `inactive_only` | `false` | Return only inactive channels |
| `public_only` | `false` | Return only public channels |
| `private_only` | `false` | Return only private channels |
| `include_pending` | `true` | Include pending open / closing channels |

Channel liquidity fields (from your node's perspective):

| Field | Meaning |
|-------|---------|
| `outbound_liquidity` / `local_balance` | Sats you can send |
| `inbound_liquidity` / `remote_balance` | Sats you can receive |
| `capacity` | Total channel size |

## Prerequisites

- Python 3.8 or higher
- One or more LND nodes running and accessible
- LND admin macaroon and TLS certificate for each configured node

## Quick Setup

### 1. Clone and Setup

```bash
git clone <your-repo>
cd python-lnd-connect

chmod +x setup.sh
./setup.sh
```

### 2. Configure Environment

Copy and edit the environment file:

```bash
cp .env.example .env
```

Example for a **Polar** regtest network with three nodes:

```bash
# Node 1 — Alice
LND_NODE_1_NAME=alice
LND_NODE_1_HOST=localhost:10001
LND_NODE_1_TLS_CERT_PATH=~/.polar/networks/<network-id>/volumes/lnd/alice/data/chain/bitcoin/regtest/tls.cert
LND_NODE_1_MACAROON_PATH=~/.polar/networks/<network-id>/volumes/lnd/alice/data/chain/bitcoin/regtest/admin.macaroon

# Node 2 — Bob (optional)
LND_NODE_2_NAME=bob
LND_NODE_2_HOST=localhost:10002
LND_NODE_2_TLS_CERT_PATH=~/.polar/networks/<network-id>/volumes/lnd/bob/data/chain/bitcoin/regtest/tls.cert
LND_NODE_2_MACAROON_PATH=~/.polar/networks/<network-id>/volumes/lnd/bob/data/chain/bitcoin/regtest/admin.macaroon

# Node 3 — Carol (optional)
LND_NODE_3_NAME=carol
LND_NODE_3_HOST=localhost:10003
LND_NODE_3_TLS_CERT_PATH=~/.polar/networks/<network-id>/volumes/lnd/carol/data/chain/bitcoin/regtest/tls.cert
LND_NODE_3_MACAROON_PATH=~/.polar/networks/<network-id>/volumes/lnd/carol/data/chain/bitcoin/regtest/admin.macaroon

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

Polar typically maps gRPC ports as `10001` (Alice), `10002` (Bob), `10003` (Carol). Get exact cert and macaroon paths from each node's **Connect** tab in Polar.

Nodes 2 and 3 are only loaded when host, TLS cert, and macaroon are all set.

### 3. Start the Server

```bash
chmod +x run.sh
./run.sh
```

## Manual Setup

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Generate gRPC Stubs

```bash
curl -o lightning.proto https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/lightning.proto
python -m grpc_tools.protoc --proto_path=. --python_out=. --grpc_python_out=. lightning.proto
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your LND node configuration
```

### 5. Start Server

```bash
source venv/bin/activate
python main.py

# Or with uvicorn for development
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Usage Examples

### List Configured Nodes

```bash
curl http://localhost:8000/nodes
```

### Check Node Health

```bash
# Node 1 (legacy route)
curl http://localhost:8000/health

# Specific node
curl http://localhost:8000/nodes/2/health
```

### Get Channel Liquidity

```bash
# All channels for Alice (node 1)
curl http://localhost:8000/nodes/1/channels

# Active channels only for Bob (node 2)
curl "http://localhost:8000/nodes/2/channels?active_only=true"
```

### Get Node Information

```bash
curl http://localhost:8000/nodes/1/info
```

### Create an Invoice

```bash
curl -X POST "http://localhost:8000/nodes/1/invoices" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1000,
    "memo": "Test invoice",
    "expiry": 3600
  }'
```

### Send a Payment

```bash
curl -X POST "http://localhost:8000/nodes/1/payments" \
  -H "Content-Type: application/json" \
  -d '{
    "payment_request": "lnbc..."
  }'
```

### Get Balances

```bash
curl http://localhost:8000/nodes/1/balance
```

### Sign a Message

```bash
curl -X POST "http://localhost:8000/nodes/1/signmessage" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello LN BOOTCAMP COTONOU!"
  }'
```

### Verify a Message

```bash
curl -X POST "http://localhost:8000/nodes/1/verifymessage" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello LN BOOTCAMP COTONOU!",
    "signature": "<signature-from-signmessage>",
    "pubkey": "<node-public-key>"
  }'
```

## API Documentation

Once the server is running, visit:

- **Interactive API Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LND_NODE_1_NAME` | `node-1` | Display name for node 1 |
| `LND_NODE_1_HOST` | falls back to `LND_HOST` | Node 1 gRPC address |
| `LND_NODE_1_TLS_CERT_PATH` | falls back to `LND_TLS_CERT_PATH` | Node 1 TLS certificate |
| `LND_NODE_1_MACAROON_PATH` | falls back to `LND_MACAROON_PATH` | Node 1 admin macaroon |
| `LND_NODE_2_*` | — | Optional second node (all three values required) |
| `LND_NODE_3_*` | — | Optional third node (all three values required) |
| `LND_HOST` | `localhost:10009` | Legacy alias for node 1 host |
| `LND_TLS_CERT_PATH` | `~/.lnd/tls.cert` | Legacy alias for node 1 TLS cert |
| `LND_MACAROON_PATH` | `~/.lnd/data/chain/bitcoin/mainnet/admin.macaroon` | Legacy alias for node 1 macaroon |
| `SERVER_HOST` | `0.0.0.0` | API server host |
| `SERVER_PORT` | `8000` | API server port |

### Standalone LND (non-Polar)

For a single mainnet or testnet node, you can still use the legacy variables:

```bash
LND_HOST=localhost:10009
LND_TLS_CERT_PATH=~/.lnd/tls.cert
LND_MACAROON_PATH=~/.lnd/data/chain/bitcoin/mainnet/admin.macaroon
```

For testnet:

```bash
LND_MACAROON_PATH=~/.lnd/data/chain/bitcoin/testnet/admin.macaroon
```

## Security Note

This API has **no HTTP authentication** and uses **admin macaroons** with full node control. It binds to `0.0.0.0` by default. Use only on local development networks (e.g. Polar regtest). Do not expose it to the public internet or use with mainnet funds without adding authentication and access controls.

## Development

### Running in Development Mode

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Project Structure

```
python-lnd-connect/
├── venv/                 # Virtual environment
├── main.py               # FastAPI app and LND gRPC client
├── lightning.proto       # LND gRPC definitions
├── lightning_pb2.py      # Generated protobuf stubs
├── lightning_pb2_grpc.py # Generated gRPC stubs
├── create_tls_cert.py    # Optional helper to write a TLS cert from base64
├── .env.example          # Multi-node configuration template
├── setup.sh              # Setup script
└── run.sh                # Start script
```
