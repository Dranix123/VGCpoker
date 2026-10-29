# 音频文件

设置 → 声音分别控制音效、音乐、语音，0% 为静音，设置保存在当前浏览器。

现在可直接使用浏览器合成的按钮、出牌、发牌、胜利、失败音效，以及预生成中文 MP3 语音（使用 macOS Tingting 生成）。预生成语音通过已启用的 Web Audio 通道播放，无需手机系统提供中文朗读；未配置文件的特殊语音才回退到系统朗读。传送带已有专属背景音乐，其他三首音乐等待放入文件；因浏览器限制，首次点击/按键后才能播放音频。

## 传送带专属音乐

`public/audio/music/conveyor.mp3`：仅在传送带对局中循环播放，包括发牌和残局阶段，不切换普通残局音乐。离开对局或结算后停止，使用设置中的音乐音量。原文件已重命名并移入此目录。

## 三首音乐

将文件放入 `public/audio/music/`，在 `public/audio/manifest.json` 的 `music` 中填写对应网址：

```json
"music": {
  "menu": "/audio/music/menu.mp3",
  "table": "/audio/music/table.mp3",
  "tension": "/audio/music/tension.mp3"
}
```

- `menu`：进入游戏、菜单、准备室和结算。
- `table`：发牌开始后的对局音乐。
- `tension`：任意玩家剩余牌数不超过其开局牌数 30% 时切换；直到本局结束保持残局音乐。

打牌音乐和残局音乐共用播放时间线，用 1.5 秒 crossfade 切换。建议这两首使用相同长度、速度、节拍起点和循环边界，以便音乐内容衔接。缺少残局音乐时继续播放打牌音乐。切到后台时暂停，返回时继续。没有填写的音乐不会请求不存在的文件。

## 替换音效

将文件放入 `public/audio/effects/`，把 `effects` 中对应的 `null` 改为网址，例如：

```json
"effects": {
  "click": "/audio/effects/click.wav",
  "play": "/audio/effects/play.wav",
  "deal": "/audio/effects/deal.wav",
  "win": "/audio/effects/win.wav",
  "lose": "/audio/effects/lose.wav"
}
```

未填文件的音效继续使用默认合成声。

## 替换语音

将文件放入 `public/audio/voices/`，在 `voices` 中替换或增加对应名称：

```json
"voices": {
  "pass": "/audio/voices/pass.mp3",
  "单张-8": "/audio/voices/single-8.mp3",
  "对子-8": "/audio/voices/pair-8.mp3",
  "三带一": "/audio/voices/triple-single.mp3",
  "三带一对": "/audio/voices/triple-pair.mp3",
  "四带两对": "/audio/voices/four-pairs.mp3",
  "炸弹": "/audio/voices/bomb.mp3",
  "叉": "/audio/voices/cross.mp3",
  "勾": "/audio/voices/hook.mp3"
}
```

单张和对子使用原始数字点数：J=11（勾）、Q=12（圈）、K=13（凯）、A=14（尖）、2=15、小王=16、大王=17；其他组合直接使用界面牌型名称。内置语音覆盖单张、对子、常见牌型、勾叉等出法，以及 3～17 张主组的带牌名称。未配置文件的语音回退到系统朗读。

支持 MP3、WAV、OGG、M4A（具体编解码支持取决于浏览器）。文件与清单更新后刷新页面。更新本次服务代码则需要先重启服务。

内置 303 段语音，包含发牌、叫分、亮牌、确认、升变、猜拳、急牌赠送、进贡选择/返还、协商答复及认输。行动音效和语音顺序播放，等待实际播放结束后向服务器确认，再允许下次行动；多人等待所有仍连接且在前台的玩家，AI 也遵守等待。静音类别直接跳过。切后台或断线的玩家不会长期阻塞牌桌。
