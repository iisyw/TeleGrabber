import os
import re
import sys
import site

def patch_telegram_bot():
    """
    Patch python-telegram-bot (v13.7) vendored urllib3 for Python 3.12 compatibility.
    """
    print("Checking for python-telegram-bot patches...")
    
    # 1. Find the telegram package location
    try:
        import telegram
        lib_dir = os.path.dirname(telegram.__file__)
    except ImportError:
        print("Error: python-telegram-bot not installed.")
        return

    vendor_dir = os.path.join(lib_dir, 'vendor', 'ptb_urllib3', 'urllib3')
    if not os.path.exists(vendor_dir):
        print(f"Vendor directory not found at {vendor_dir}. Skipping.")
        return

    print(f"Found vendored urllib3 at: {vendor_dir}")

    # 2. Patch six.moves relative imports
    # This fixes: ModuleNotFoundError: No module named 'telegram.vendor.ptb_urllib3.urllib3.packages.six.moves'
    print("Patching six.moves imports...")
    patched_count = 0
    for root, dirs, files in os.walk(vendor_dir):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Replace 'from .packages.six.moves' or 'from ..packages.six.moves' with 'from six.moves'
                new_content = re.sub(r'from \.*packages\.six\.moves', 'from six.moves', content)
                
                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    patched_count += 1
    print(f"Patched {patched_count} files for six.moves.")

    # 3. Patch util/ssl_.py for PROTOCOL_SSLv23 and wrap_socket removal
    # This fixes: name 'PROTOCOL_SSLv23' is not defined
    ssl_file = os.path.join(vendor_dir, 'util', 'ssl_.py')
    if os.path.exists(ssl_file):
        print(f"Patching {ssl_file} for Python 3.12 SSL...")
        with open(ssl_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        target = r'try:  # Test for SSL features\s+import ssl\s+from ssl import wrap_socket, CERT_NONE, PROTOCOL_SSLv23\s+from ssl import HAS_SNI  # Has SNI\?\s+except ImportError:\s+pass'
        replacement = '''try:  # Test for SSL features
    import ssl
    CERT_NONE = ssl.CERT_NONE
    PROTOCOL_SSLv23 = getattr(ssl, 'PROTOCOL_SSLv23', getattr(ssl, 'PROTOCOL_TLS', 2))
    wrap_socket = getattr(ssl, 'wrap_socket', None)
    HAS_SNI = getattr(ssl, 'HAS_SNI', False)
except ImportError:
    pass'''
        
        new_content = re.sub(target, replacement, content, flags=re.MULTILINE)
        
        if new_content != content:
            with open(ssl_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print("Successfully patched util/ssl_.py")
        else:
            # Check if already patched
            if 'getattr(ssl, \'PROTOCOL_SSLv23\'' in content:
                print("util/ssl_.py already patched.")
            else:
                print("Warning: Could not find target import block in util/ssl_.py. Maybe it's a different version?")
    else:
        print(f"Warning: {ssl_file} not found.")

    print("Patching complete.")

if __name__ == "__main__":
    patch_telegram_bot()
