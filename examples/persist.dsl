flow main
state start
  load name from "data/state.json"
  reply "欢迎～"
  ask name "你叫什么名字？："
  reply "你好，{{name}}！已经帮你记住这个名字。"
  save name to "data/state.json"
  reply "再见～"
