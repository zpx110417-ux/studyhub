"""本地开发入口：python run.py，访问 http://127.0.0.1:5000"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # host="0.0.0.0" 表示监听本机所有网卡，局域网内其他设备可通过 Mac 的 IP 访问
    # 端口用 5001：macOS 的"AirPlay 接收器"默认占用 5000，会冲突
    app.run(debug=True, host="0.0.0.0", port=5001)
