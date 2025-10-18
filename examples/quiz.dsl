flow main
state start
  reply "欢迎来到小问答～"
  ask name "你叫什么名字？"
  reply "你好，{{name}}！"
  reply "你喜欢 Python 吗？(yes/no)"
  ask like "请输入"
  if like == "yes" goto love
  goto end

state love
  reply "太棒了，{{name}} 也是 Python 党！"
  goto end

state end
  reply "演示结束，感谢参与～"
