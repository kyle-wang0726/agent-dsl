flow main
state start
  ask score "原始分数："
  if score + 10 >= 90 and (score >= 60) {
    reply "优秀或加分达标：{{score}}"
  } elif score >= 60 {
    reply "及格：{{score}}"
  } else {
    reply "不及格：{{score}}"
  }
  goto end

state end
  reply "流程结束"
