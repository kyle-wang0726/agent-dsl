flow main
state start
  reply "您好，这里是 DSL v0 的演示。"
  reply "现在跳转到 end 状态。"
  goto end
state end
  reply "演示结束，再见！"
