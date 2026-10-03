# Task: write a sealed test key

You are the key writer. Read `brief.md` first and follow it exactly.

- The cases are in `part-1.md` to `part-4.md`. For each part file, write
  `key-part-N.json` in this folder, holding that part's cases and nothing else.
- Use only the files in this folder. Do not browse the web, open other folders, or use
  earlier conversations or memories.
- `corpus/` holds the whole text of every source (`corpus/index.md` lists their
  addresses). Use it only to confirm that an `absent` case's detail is stated nowhere.
- You may write small scripts in this folder to check your work. Do not edit `brief.md`,
  `AGENTS.md`, the part files or `corpus/`.

Before you finish, check every part file's key:
1. The JSON is valid and holds every case of the part once, with its planned id and type.
2. Every quote is copied exactly from its source as shown in the part file (spaces aside),
   has 5 to 40 words, and a PDF quote has the page number of the `[page N]` marker above
   it.
3. Every source of an answered case is quoted at least once.
4. Each `absent` case's `absence_terms` appear nowhere in `corpus/`.
5. No wording mentions a source id, a page marker or the word "excerpt".
