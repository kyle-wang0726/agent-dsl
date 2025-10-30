flow main
  state start
    load balance from "data/state.json"

    reply "您好，这里是运营商自助服务。可以说：充值、查余额、退出。"
    ask query "请输入您的问题："

    if contains(query, "充值") {
      goto topup
    }
    elif contains(query, "余额") {
      goto balance
    }
    elif contains(query, "退出") {
      goto end
    }
    # 注意：这里不要写 else 块；留空让运行时先尝试 LLM，失败则跳到 fallback

  state topup
    ask amount "请输入充值金额（元）："
    if balance == "" {
      set balance = 0
    }
    set balance = int(balance) + int(amount)
    save balance to "data/state.json"
    reply "充值成功，本次充值 {{ amount }} 元，当前余额：{{ balance }} 元。"
    goto start

  state balance
    if balance == "" {
      set balance = 0
    }
    reply "您的当前余额为：{{ balance }} 元。"
    goto start

  state fallback
    reply "未能识别您的需求：{{ query | trim }}。试试：'充值100' 或 '查余额'。"
    goto start

  state end
    reply "已退出，自助服务感谢使用～"
