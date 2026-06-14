from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import grpc
import os
import codecs
from typing import Optional, Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import LND gRPC stubs (you'll need to generate these)
# Run: python -m grpc_tools.protoc --proto_path=. --python_out=. --grpc_python_out=. lightning.proto
try:
    import lightning_pb2 as ln
    import lightning_pb2_grpc as lnrpc
except ImportError:
    print("Warning: LND gRPC stubs not found. Please generate them using:")
    print("python -m grpc_tools.protoc --proto_path=. --python_out=. --grpc_python_out=. lightning.proto")
    print("Make sure to activate your virtual environment first!")

app = FastAPI(
    title="LND Lightning API",
    version="1.1.0",
    description="Open Lightning Network API for up to 3 LND node operations",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_NODES = 3


class NodeConfig:
    def __init__(self, node_id: str, name: str, host: str, tls_cert_path: str, macaroon_path: str):
        self.node_id = node_id
        self.name = name
        self.host = host
        self.tls_cert_path = tls_cert_path
        self.macaroon_path = macaroon_path


class Config:
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
    nodes: Dict[str, NodeConfig] = {}

    @classmethod
    def _load_node(cls, node_id: str, defaults: Optional[Dict[str, str]] = None) -> Optional[NodeConfig]:
        defaults = defaults or {}
        prefix = f"LND_NODE_{node_id}_"
        host = os.getenv(f"{prefix}HOST") or defaults.get("host")
        tls_cert_path = os.getenv(f"{prefix}TLS_CERT_PATH") or defaults.get("tls_cert_path")
        macaroon_path = os.getenv(f"{prefix}MACAROON_PATH") or defaults.get("macaroon_path")
        name = os.getenv(f"{prefix}NAME") or defaults.get("name") or f"node-{node_id}"

        if not host or not tls_cert_path or not macaroon_path:
            return None

        return NodeConfig(
            node_id=node_id,
            name=name,
            host=host,
            tls_cert_path=tls_cert_path,
            macaroon_path=macaroon_path,
        )

    @classmethod
    def load(cls):
        node_1_defaults = {
            "host": os.getenv("LND_HOST", "localhost:10009"),
            "tls_cert_path": os.getenv("LND_TLS_CERT_PATH", "~/.lnd/tls.cert"),
            "macaroon_path": os.getenv(
                "LND_MACAROON_PATH",
                "~/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
            ),
            "name": os.getenv("LND_NODE_1_NAME", "node-1"),
        }

        for node_id in ("1", "2", "3"):
            defaults = node_1_defaults if node_id == "1" else None
            node = cls._load_node(node_id, defaults)
            if node:
                cls.nodes[node_id] = node

        if not cls.nodes:
            raise RuntimeError("No LND nodes configured. Set LND_NODE_1_* or legacy LND_* variables.")

    @classmethod
    def validate(cls):
        print("Starting LND Lightning API Server")
        print(f"Configured nodes: {len(cls.nodes)}")
        for node_id, node in cls.nodes.items():
            print(f"  Node {node_id} ({node.name}): {node.host}")
        print(f"Server will run on: http://{cls.SERVER_HOST}:{cls.SERVER_PORT}")
        print(f"API docs available at: http://{cls.SERVER_HOST}:{cls.SERVER_PORT}/docs")


config = Config()
config.load()
config.validate()


class InvoiceRequest(BaseModel):
    amount: int
    memo: Optional[str] = ""
    expiry: Optional[int] = 3600


class PaymentRequest(BaseModel):
    payment_request: str
    amount: Optional[int] = None


class WalletInfo(BaseModel):
    alias: str
    identity_pubkey: str
    num_active_channels: int
    num_peers: int
    block_height: int
    synced_to_chain: bool
    synced_to_graph: bool
    version: str


class SignMessageRequest(BaseModel):
    message: str


class LNDConnection:
    def __init__(self, node: NodeConfig):
        self.node = node
        self.channel = None
        self.stub = None
        self.macaroon = None
        self._connect()

    def _connect(self):
        try:
            tls_cert_path = os.path.expanduser(self.node.tls_cert_path)
            with open(tls_cert_path, "rb") as f:
                cert = f.read()

            macaroon_path = os.path.expanduser(self.node.macaroon_path)
            with open(macaroon_path, "rb") as f:
                macaroon_bytes = f.read()
                self.macaroon = codecs.encode(macaroon_bytes, "hex")

            ssl_creds = grpc.ssl_channel_credentials(cert)
            self.channel = grpc.secure_channel(self.node.host, ssl_creds)
            self.stub = lnrpc.LightningStub(self.channel)
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to node {self.node.node_id} ({self.node.name}): {e}"
            ) from e

    def _get_metadata(self):
        return [("macaroon", self.macaroon)]

    def get_info(self):
        try:
            request = ln.GetInfoRequest()
            return self.stub.GetInfo(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get node info: {str(e)}")

    def create_invoice(self, amount: int, memo: str = "", expiry: int = 3600):
        try:
            request = ln.Invoice(value=amount, memo=memo, expiry=expiry)
            return self.stub.AddInvoice(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")

    def lookup_invoice(self, r_hash: str):
        try:
            r_hash_bytes = codecs.decode(r_hash, "hex")
            request = ln.PaymentHash(r_hash=r_hash_bytes)
            return self.stub.LookupInvoice(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to lookup invoice: {str(e)}")

    def send_payment(self, payment_request: str, amount: int = None):
        try:
            request = ln.SendRequest(payment_request=payment_request, amt=amount)
            return self.stub.SendPaymentSync(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send payment: {str(e)}")

    def list_invoices(self, num_max_invoices: int = 100):
        try:
            request = ln.ListInvoiceRequest(num_max_invoices=num_max_invoices)
            return self.stub.ListInvoices(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list invoices: {str(e)}")

    def list_payments(self, max_payments: int = 100):
        try:
            request = ln.ListPaymentsRequest(max_payments=max_payments)
            return self.stub.ListPayments(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list payments: {str(e)}")

    def get_balance(self):
        try:
            request = ln.WalletBalanceRequest()
            return self.stub.WalletBalance(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")

    def get_channel_balance(self):
        try:
            request = ln.ChannelBalanceRequest()
            return self.stub.ChannelBalance(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get channel balance: {str(e)}")

    def list_channels(
        self,
        active_only: bool = False,
        inactive_only: bool = False,
        public_only: bool = False,
        private_only: bool = False,
        peer_alias_lookup: bool = True,
    ):
        try:
            request = ln.ListChannelsRequest(
                active_only=active_only,
                inactive_only=inactive_only,
                public_only=public_only,
                private_only=private_only,
                peer_alias_lookup=peer_alias_lookup,
            )
            return self.stub.ListChannels(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list channels: {str(e)}")

    def list_pending_channels(self):
        try:
            request = ln.PendingChannelsRequest()
            return self.stub.PendingChannels(request, metadata=self._get_metadata())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list pending channels: {str(e)}")


class LNDConnectionManager:
    def __init__(self, nodes: Dict[str, NodeConfig]):
        self.nodes = nodes
        self.connections: Dict[str, LNDConnection] = {}
        self.errors: Dict[str, str] = {}

        for node_id, node_config in nodes.items():
            try:
                self.connections[node_id] = LNDConnection(node_config)
                print(f"Connected to node {node_id} ({node_config.name})")
            except Exception as e:
                self.errors[node_id] = str(e)
                print(f"Failed to connect to node {node_id} ({node_config.name}): {e}")

        if not self.connections:
            raise RuntimeError("Could not connect to any configured LND node.")

    def get(self, node_id: str) -> LNDConnection:
        if node_id not in self.nodes:
            raise HTTPException(
                status_code=404,
                detail=f"Node '{node_id}' is not configured. Available nodes: {', '.join(self.nodes)}",
            )
        if node_id in self.errors:
            raise HTTPException(
                status_code=503,
                detail=f"Node '{node_id}' is unavailable: {self.errors[node_id]}",
            )
        return self.connections[node_id]

    def list_nodes(self):
        result = []
        for node_id, node in self.nodes.items():
            result.append(
                {
                    "id": node_id,
                    "name": node.name,
                    "host": node.host,
                    "connected": node_id in self.connections,
                    "error": self.errors.get(node_id),
                }
            )
        return result


lnd_manager = LNDConnectionManager(config.nodes)


def _health_payload(lnd: LNDConnection, node_id: str):
    try:
        info = lnd.get_info()
        return {
            "node_id": node_id,
            "node_name": lnd.node.name,
            "status": "healthy",
            "node_alias": info.alias,
            "synced_to_chain": info.synced_to_chain,
            "synced_to_graph": info.synced_to_graph,
            "block_height": info.block_height,
        }
    except Exception as e:
        return {
            "node_id": node_id,
            "node_name": lnd.node.name,
            "status": "unhealthy",
            "error": str(e),
        }


def _wallet_info(lnd: LNDConnection) -> WalletInfo:
    info = lnd.get_info()
    return WalletInfo(
        alias=info.alias,
        identity_pubkey=info.identity_pubkey,
        num_active_channels=info.num_active_channels,
        num_peers=info.num_peers,
        block_height=info.block_height,
        synced_to_chain=info.synced_to_chain,
        synced_to_graph=info.synced_to_graph,
        version=info.version,
    )


def _balance_payload(lnd: LNDConnection):
    wallet_balance = lnd.get_balance()
    channel_balance = lnd.get_channel_balance()
    return {
        "wallet_balance": {
            "total_balance": wallet_balance.total_balance,
            "confirmed_balance": wallet_balance.confirmed_balance,
            "unconfirmed_balance": wallet_balance.unconfirmed_balance,
        },
        "channel_balance": {
            "balance": channel_balance.balance,
            "pending_open_balance": channel_balance.pending_open_balance,
        },
    }


def _invoice_payload(invoice):
    return {
        "payment_request": invoice.payment_request,
        "r_hash": codecs.encode(invoice.r_hash, "hex").decode(),
        "add_index": invoice.add_index,
        "amount": invoice.value,
        "memo": invoice.memo,
        "expiry": invoice.expiry,
        "settled": invoice.settled,
        "creation_date": invoice.creation_date,
        "settle_date": invoice.settle_date if invoice.settled else None,
    }


def _amount_sat(amount) -> int:
    if amount is None:
        return 0
    return getattr(amount, "sat", 0) or 0


def _channel_payload(channel):
    return {
        "active": channel.active,
        "chan_id": str(channel.chan_id),
        "channel_point": channel.channel_point,
        "remote_pubkey": channel.remote_pubkey,
        "peer_alias": channel.peer_alias,
        "capacity": channel.capacity,
        "local_balance": channel.local_balance,
        "remote_balance": channel.remote_balance,
        "outbound_liquidity": channel.local_balance,
        "inbound_liquidity": channel.remote_balance,
        "unsettled_balance": channel.unsettled_balance,
        "commit_fee": channel.commit_fee,
        "fee_per_kw": channel.fee_per_kw,
        "private": channel.private,
        "initiator": channel.initiator,
        "chan_status_flags": channel.chan_status_flags,
        "total_satoshis_sent": channel.total_satoshis_sent,
        "total_satoshis_received": channel.total_satoshis_received,
        "num_updates": channel.num_updates,
        "pending_htlcs_count": len(channel.pending_htlcs),
        "zero_conf": channel.zero_conf,
        "memo": channel.memo,
    }


def _pending_channel_base(channel):
    return {
        "remote_pubkey": channel.remote_node_pub,
        "channel_point": channel.channel_point,
        "capacity": channel.capacity,
        "local_balance": channel.local_balance,
        "remote_balance": channel.remote_balance,
        "outbound_liquidity": channel.local_balance,
        "inbound_liquidity": channel.remote_balance,
        "private": channel.private,
        "initiator": channel.initiator.name if channel.initiator else None,
        "chan_status_flags": channel.chan_status_flags,
        "memo": channel.memo,
    }


def _channels_payload(
    lnd: LNDConnection,
    include_pending: bool = True,
    active_only: bool = False,
    inactive_only: bool = False,
    public_only: bool = False,
    private_only: bool = False,
):
    response = lnd.list_channels(
        active_only=active_only,
        inactive_only=inactive_only,
        public_only=public_only,
        private_only=private_only,
        peer_alias_lookup=True,
    )
    channels = [_channel_payload(channel) for channel in response.channels]

    total_capacity = sum(channel.capacity for channel in response.channels)
    total_outbound = sum(channel.local_balance for channel in response.channels)
    total_inbound = sum(channel.remote_balance for channel in response.channels)
    total_unsettled = sum(channel.unsettled_balance for channel in response.channels)

    channel_balance = lnd.get_channel_balance()
    summary = {
        "open_channel_count": len(channels),
        "active_channel_count": sum(1 for channel in response.channels if channel.active),
        "total_capacity": total_capacity,
        "total_outbound_liquidity": total_outbound,
        "total_inbound_liquidity": total_inbound,
        "total_unsettled_balance": total_unsettled,
        "aggregate_local_balance": _amount_sat(channel_balance.local_balance),
        "aggregate_remote_balance": _amount_sat(channel_balance.remote_balance),
        "aggregate_unsettled_local_balance": _amount_sat(channel_balance.unsettled_local_balance),
        "aggregate_unsettled_remote_balance": _amount_sat(channel_balance.unsettled_remote_balance),
        "pending_open_local_balance": _amount_sat(channel_balance.pending_open_local_balance),
        "pending_open_remote_balance": _amount_sat(channel_balance.pending_open_remote_balance),
    }

    payload = {
        "summary": summary,
        "channels": channels,
    }

    if include_pending:
        pending = lnd.list_pending_channels()
        payload["pending"] = {
            "total_limbo_balance": pending.total_limbo_balance,
            "pending_open": [
                {
                    **_pending_channel_base(item.channel),
                    "commit_fee": item.commit_fee,
                    "fee_per_kw": item.fee_per_kw,
                    "funding_expiry_blocks": item.funding_expiry_blocks,
                }
                for item in pending.pending_open_channels
            ],
            "pending_force_closing": [
                {
                    **_pending_channel_base(item.channel),
                    "closing_txid": item.closing_txid,
                    "limbo_balance": item.limbo_balance,
                    "maturity_height": item.maturity_height,
                    "blocks_til_maturity": item.blocks_til_maturity,
                    "recovered_balance": item.recovered_balance,
                }
                for item in pending.pending_force_closing_channels
            ],
            "waiting_close": [
                {
                    **_pending_channel_base(item.channel),
                    "limbo_balance": item.limbo_balance,
                    "closing_txid": item.closing_txid,
                }
                for item in pending.waiting_close_channels
            ],
        }

    return payload


@app.get("/")
async def root():
    return {
        "message": "LND Lightning API Server",
        "version": "1.1.0",
        "description": "Open API for Lightning Network operations (up to 3 nodes)",
        "nodes": "/nodes",
        "docs": "/docs",
        "health": "/health",
        "channels": "/channels",
        "node_routes": "/nodes/{node_id}/health",
    }


@app.get("/nodes")
async def list_nodes():
    return {"nodes": lnd_manager.list_nodes(), "max_nodes": MAX_NODES}


@app.get("/health")
async def health_check_default():
    lnd = lnd_manager.get("1")
    return _health_payload(lnd, "1")


@app.get("/nodes/{node_id}/health")
async def health_check(node_id: str):
    lnd = lnd_manager.get(node_id)
    return _health_payload(lnd, node_id)


@app.get("/info", response_model=WalletInfo)
async def get_node_info_default():
    return _wallet_info(lnd_manager.get("1"))


@app.get("/nodes/{node_id}/info", response_model=WalletInfo)
async def get_node_info(node_id: str):
    return _wallet_info(lnd_manager.get(node_id))


@app.get("/balance")
async def get_balances_default():
    return _balance_payload(lnd_manager.get("1"))


@app.get("/nodes/{node_id}/balance")
async def get_balances(node_id: str):
    return _balance_payload(lnd_manager.get(node_id))


@app.get("/channels")
async def list_channels_default(include_pending: bool = True):
    lnd = lnd_manager.get("1")
    return {"node_id": "1", **_channels_payload(lnd, include_pending=include_pending)}


@app.get("/nodes/{node_id}/channels")
async def list_channels(
    node_id: str,
    active_only: bool = False,
    inactive_only: bool = False,
    public_only: bool = False,
    private_only: bool = False,
    include_pending: bool = True,
):
    lnd = lnd_manager.get(node_id)
    return {
        "node_id": node_id,
        **_channels_payload(
            lnd,
            include_pending=include_pending,
            active_only=active_only,
            inactive_only=inactive_only,
            public_only=public_only,
            private_only=private_only,
        ),
    }


@app.post("/invoices")
async def create_invoice_default(invoice_req: InvoiceRequest):
    return await create_invoice("1", invoice_req)


@app.post("/nodes/{node_id}/invoices")
async def create_invoice(node_id: str, invoice_req: InvoiceRequest):
    lnd = lnd_manager.get(node_id)
    response = lnd.create_invoice(
        amount=invoice_req.amount,
        memo=invoice_req.memo,
        expiry=invoice_req.expiry,
    )
    return {
        "node_id": node_id,
        "payment_request": response.payment_request,
        "r_hash": codecs.encode(response.r_hash, "hex").decode(),
        "add_index": response.add_index,
    }


@app.get("/invoices/{r_hash}")
async def get_invoice_default(r_hash: str):
    return await get_invoice("1", r_hash)


@app.get("/nodes/{node_id}/invoices/{r_hash}")
async def get_invoice(node_id: str, r_hash: str):
    lnd = lnd_manager.get(node_id)
    invoice = lnd.lookup_invoice(r_hash)
    return {"node_id": node_id, **_invoice_payload(invoice)}


@app.get("/invoices")
async def list_invoices_default(limit: int = 100):
    return await list_invoices("1", limit)


@app.get("/nodes/{node_id}/invoices")
async def list_invoices(node_id: str, limit: int = 100):
    lnd = lnd_manager.get(node_id)
    invoices = lnd.list_invoices(num_max_invoices=limit)
    return {
        "node_id": node_id,
        "invoices": [_invoice_payload(invoice) for invoice in invoices.invoices],
    }


@app.post("/payments")
async def send_payment_default(payment_req: PaymentRequest):
    return await send_payment("1", payment_req)


@app.post("/nodes/{node_id}/payments")
async def send_payment(node_id: str, payment_req: PaymentRequest):
    lnd = lnd_manager.get(node_id)
    response = lnd.send_payment(
        payment_request=payment_req.payment_request,
        amount=payment_req.amount,
    )

    if response.payment_error:
        raise HTTPException(status_code=400, detail=response.payment_error)

    return {
        "node_id": node_id,
        "payment_hash": codecs.encode(response.payment_hash, "hex").decode(),
        "payment_preimage": codecs.encode(response.payment_preimage, "hex").decode(),
        "payment_route": {
            "total_fees": response.payment_route.total_fees,
            "total_amt": response.payment_route.total_amt,
            "total_time_lock": response.payment_route.total_time_lock,
        },
    }


@app.get("/payments")
async def list_payments_default(limit: int = 100):
    return await list_payments("1", limit)


@app.get("/nodes/{node_id}/payments")
async def list_payments(node_id: str, limit: int = 100):
    lnd = lnd_manager.get(node_id)
    payments = lnd.list_payments(max_payments=limit)

    result = []
    for payment in payments.payments:
        result.append(
            {
                "payment_hash": payment.payment_hash,
                "payment_preimage": payment.payment_preimage,
                "value": payment.value,
                "creation_date": payment.creation_date,
                "fee": payment.fee,
                "payment_request": payment.payment_request,
                "status": payment.status.name,
            }
        )

    return {"node_id": node_id, "payments": result}


@app.get("/decode/{payment_request}")
async def decode_payment_request_default(payment_request: str):
    return await decode_payment_request("1", payment_request)


@app.get("/nodes/{node_id}/decode/{payment_request}")
async def decode_payment_request(node_id: str, payment_request: str):
    lnd = lnd_manager.get(node_id)
    try:
        request = ln.PayReqString(pay_req=payment_request)
        response = lnd.stub.DecodePayReq(request, metadata=lnd._get_metadata())
        return {
            "node_id": node_id,
            "destination": response.destination,
            "payment_hash": response.payment_hash,
            "num_satoshis": response.num_satoshis,
            "timestamp": response.timestamp,
            "expiry": response.expiry,
            "description": response.description,
            "description_hash": response.description_hash,
            "fallback_addr": response.fallback_addr,
            "cltv_expiry": response.cltv_expiry,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode payment request: {str(e)}")


@app.post("/signmessage")
async def sign_message_default(data: SignMessageRequest):
    return await sign_message("1", data)


@app.post("/nodes/{node_id}/signmessage")
async def sign_message(node_id: str, data: SignMessageRequest):
    lnd = lnd_manager.get(node_id)
    msg = data.message
    if not msg:
        return JSONResponse(content={"error": "Message is required"}, status_code=400)

    try:
        sign_req = ln.SignMessageRequest(msg=msg.encode("utf-8"))
        sign_resp = lnd.stub.SignMessage(sign_req, metadata=lnd._get_metadata())
        return JSONResponse(content={"node_id": node_id, "signature": sign_resp.signature}, status_code=200)
    except grpc.RpcError as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/verifymessage")
async def verify_message_default(data: dict = Body(...)):
    return await verify_message("1", data)


@app.post("/nodes/{node_id}/verifymessage")
async def verify_message(node_id: str, data: dict = Body(...)):
    lnd = lnd_manager.get(node_id)
    msg = data.get("message")
    signature = data.get("signature")
    pubkey = data.get("pubkey")
    if not msg or not signature or not pubkey:
        return JSONResponse(
            content={"error": "Message, signature, and pubkey are required"},
            status_code=400,
        )

    try:
        verify_req = ln.VerifyMessageRequest(msg=msg.encode("utf-8"), signature=signature)
        verify_resp = lnd.stub.VerifyMessage(verify_req, metadata=lnd._get_metadata())
        return JSONResponse(content={"node_id": node_id, "valid": verify_resp.valid}, status_code=200)
    except grpc.RpcError as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT)
