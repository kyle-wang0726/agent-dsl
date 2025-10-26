flow main
state start
  set name = " wxw "
  set bonus = max(5, 2*3)             # => 6
  set total = score * 1.2 + bonus     # 表达式 set
  if total >= 90 and upper(name) == "WXW" {
    reply "优秀，总分：{{total}}，用户：{{ name | trim | upper }}"
  } elif score >= 60 or true {
    reply "及格，总分：{{total}}，你好：{{ name | default:\"游客\" | trim }}"
  } else {
    reply "未通过"
  }
  goto end

state end
  reply "流程结束"
