# 輸出風格整理(Output Styles)

你丟的兩個東西整理後放在這裡。**兩個的目的一樣(叫 Claude 講人話),但機制不一樣**——一個是常駐的、一個是隨叫隨到的。

## 目前有什麼

| 檔案 | 種類 | 什麼時候生效 | 語言 |
|---|---|---|---|
| `.claude/output-styles/eli5.md` | Output style | 切換後**一直**生效 | 英文(原版照抄) |
| `.claude/output-styles/eli5-zh.md` | Output style | 切換後**一直**生效 | 繁體中文 ← **建議用這個** |
| `.claude/skills/wait-what/SKILL.md` | Skill(指令) | 你打 `/wait-what` 才生效 | 繁體中文 |

## 怎麼用

**常駐版**(套上去之後每一句回覆都會變簡單):

```
/output-style eli5-zh
```

想切回原本的:

```
/output-style default
```

**隨叫隨到版**(平常正常講,只有某一段聽不懂時再打):

```
/wait-what
```

## 為什麼多做了一個繁中版

Output style 會**取代**Claude Code 原本的系統提示。原版 `eli5.md` 整份是英文,套下去很可能連回覆都變英文——那跟 `CLAUDE.md` 裡「全程繁體中文」的規則直接打架。所以原版照抄保留一份給你對照,實際要用的是 `eli5-zh.md`,內容一樣但加了繁中規則、以及你既有的習慣(先講結果、宣稱完成要附證據、二選一要直接推薦)。

## 來源與更正

- `eli5.md`:照你給的截圖逐字轉錄,一個字沒改(含 `keep-coding-instructions: true`)。
- `wait-what`:來自 [mattpocock/skills](https://github.com/mattpocock/skills)(MIT License)。**該 repo 裡沒有 output style**,它是 skill 集合;`/wait-what` 是裡面唯一跟 ELI5 同一個目的的東西,所以我把它當成你說的「第二個」整理進來。原版要求引用 `CONTEXT.md` 的統一用語,本專案沒有這個檔,已改指向 `CLAUDE.md`,並加上繁中規則。

如果你要的是整包 Matt Pocock 的 skills(`/grill-me` 逼問需求、`/tdd`、`/handoff` 交接文件…共約 30 支),那是另一件事,跟我說:

```
幫我把 mattpocock/skills 整包裝進專案
```
