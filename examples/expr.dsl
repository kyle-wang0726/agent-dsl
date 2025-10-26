flow main
state start
  ask score "原始分数？："
  if score + 10 >= 80 {
    reply "加 10 分后达标：{{score}}"
  } else {
    reply "仍未达标：{{score}}"
  }
  if (score * 2) < (150 - 10) {
    reply "额外判断成立（示例）"
  }
  goto end

state end
  reply "流程结束"
