# 音频文件

设置 → 声音分别控制音效、音乐、语音，0% 为静音，设置保存在当前浏览器。

现在可直接使用浏览器合成的按钮、出牌、发牌、胜利、失败音效，以及系统中文朗读。支持中文朗读的系统才能听到默认语音。音乐等待放入文件；因浏览器限制，首次点击/按键后才能播放音频。

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

将文件放入 `public/audio/voices/`，在 `voices` 中增加对应名称：

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

单张和对子使用原始数字点数：J=11、Q=12、K=13、A=14、2=15、小王=16、大王=17；其他组合直接使用界面牌型名称。未配置的语音继续使用系统朗读。

支持 MP3、WAV、OGG、M4A（具体编解码支持取决于浏览器）。文件与清单更新后刷新页面。更新本次服务代码则需要先重启服务。
