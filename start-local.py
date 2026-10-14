from pathlib import Path
import threading,urllib.request,webbrowser
from server import main
URL='http://127.0.0.1:8765'
def existing():
 try:
  with urllib.request.urlopen(URL+'/api/session',timeout=2) as r:return b'"version": 2' in r.read()
 except Exception:return False
def open_ready():
 import time
 for _ in range(30):
  if existing():
   webbrowser.open(URL);return
  time.sleep(.25)
if existing():
 print('工作台已经在运行，正在打开。');webbrowser.open(URL)
else:
 threading.Thread(target=open_ready,daemon=True).start()
 try:main()
 except OSError as e:
  print('无法启动。若8765端口仍是旧版工作台，请先关闭旧版服务后重新打开。错误：'+str(e))
  input('按回车关闭')
