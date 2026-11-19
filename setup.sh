#!/bin/bash

# LND Lightning API Setup Script
echo "🚀 Setting up LND Lightning API Server..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Create virtual environment
echo "📦 Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip3 install --upgrade pip

# Install dependencies
echo "📥 Installing dependencies..."
pip3 install -r requirements.txt

# Download LND protobuf definition
echo "📡 Downloading LND protobuf definition..."
if [ ! -f "lightning.proto" ]; then
    curl -o lightning.proto https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/lightning.proto
else
    echo "⚠️  lightning.proto already exists, skipping download"
fi

# Generate gRPC stubs
echo "🔧 Generating gRPC stubs..."
python -m grpc_tools.protoc --proto_path=. --python_out=. --grpc_python_out=. lightning.proto

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "✅ Created .env file. Please edit it with your LND configuration."
else
    echo "⚠️  .env file already exists"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Edit the .env file with your LND node configuration"
echo "2. Make sure your LND node is running and accessible"
echo "3. Start the API server:"
echo ""
echo "   # Activate virtual environment (if not already active)"
echo "   source venv/bin/activate"
echo ""
echo "   # Start the server"
echo "   python main.py"
echo ""
echo "   # Or use uvicorn directly"
echo "   uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "🌐 API will be available at: http://localhost:8000"
echo "📚 API documentation: http://localhost:8000/docs"