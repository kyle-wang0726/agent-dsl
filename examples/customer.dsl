flow main
  state start
    reply "您好，这里是智能客服中心。请问您要办理什么业务？"
    ask query "请输入您的问题："

    # 规则优先（contains 来自解释器白名单函数）
    if contains(query, "退款") {
      goto refund
    }
    elif contains(query, "投诉") {
      goto complaint
    }
    elif contains(query, "余额") {
      goto balance
    }
    else {
      reply "好的，我来为您判断最合适的部门处理……"
      # 不写 goto，若前面都没命中，解释器会使用 LLM 建议做兜底跳转
    }

  state refund
    reply "您想申请退款，对吗？系统已为您转到退款专员。"
    goto end

  state complaint
    reply "已为您连接投诉专员，请稍候。"
    goto end

  state balance
    reply "您的账户余额为 98.00 元。"
    goto end

  state end
    reply "感谢使用，再见！"
    
  state fallback
    reply "我还没理解您的需求。可选业务：退款、投诉、余额查询。"
    reply "可以这样说：我要退款 / 我要投诉 / 查余额。"
    goto end
