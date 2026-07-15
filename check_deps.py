import sys

def check_dependencies():
    required = [
        'aiogram', 'openai', 'supabase', 'dotenv', 
        'pandas', 'openpyxl', 'httpx', 'rembg', 
        'PIL', 'yookassa'
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package)
            print(f"✅ {package} - OK")
        except ImportError:
            print(f"❌ {package} - MISSING")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️ Missing packages: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        sys.exit(1)
    else:
        print("\n✅ All dependencies installed successfully!")

if __name__ == "__main__":
    check_dependencies()