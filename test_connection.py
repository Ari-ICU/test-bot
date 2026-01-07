#!/usr/bin/env python3
"""
Quick diagnostic tool to test MT5 EA connection
"""
import socket
import time

HOST = '127.0.0.1'
PORT = 8001

def test_server():
    """Test if the Python server is accepting connections"""
    print(f"🔍 Testing connection to {HOST}:{PORT}...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((HOST, PORT))
        print("✅ Successfully connected to server!")
        
        # Send a POLL command like the EA does
        print("📤 Sending POLL command...")
        sock.sendall(b"POLL\n")
        
        # Try to receive response
        print("📥 Waiting for response...")
        sock.settimeout(2)
        try:
            data = sock.recv(4096)
            response = data.decode('utf-8')
            print(f"✅ Received response: {repr(response)}")
        except socket.timeout:
            print("⚠️  No response received (timeout)")
        
        sock.close()
        print("✅ Connection test complete!")
        return True
        
    except ConnectionRefusedError:
        print("❌ Connection refused! Is the Python bot running?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    test_server()
