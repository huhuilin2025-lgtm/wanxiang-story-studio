#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
for studio_python in /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [[ -x "$studio_python" ]]; then
    "$studio_python" start-local.py
    exit $?
  fi
done
print '未找到Python3，请先安装Python3。'
read 'studio_exit?按回车关闭'
