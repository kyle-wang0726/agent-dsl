flow main
state start
  ask score "分数是多少？："
  if score >= 60 {
    reply "恭喜通过，分数：{{score}}"
  } else {
    reply "很遗憾未通过，分数：{{score}}"
  }
  goto end

state end
  reply "流程结束～"
