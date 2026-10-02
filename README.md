# Concordance

Concordance is a dictionary-based keyword-in-context tool for content analysis. Given a corpus of documents and a coding dictionary of terms grouped into categories, it retrieves every occurrence of each term in its sentence, traces each to its document and metadata, produces frequency counts by category and by document group, and records every analytic decision so the analysis can be reproduced and audited.

It reads the documents. It does not change them. It also does not add to, remove from, or rewrite your term list.

## What you need

- Python 3. It was tested on a Mac with Python 3.14.2 and should work with other recent versions of Python 3, but it has not been tested on Windows or Linux. The python.org installer includes the window system this tool uses.
- A folder of documents. The tool can read `.txt`, `.md`, `.docx`, `.pdf`, `.html`, and `.htm` files.
- A term list. This is a spreadsheet saved as CSV, with three columns: `category`, `term`, and `stem`. `example_terms.csv` in this folder is a small made-up list you can copy. A category is a topic, such as Gardening. A term is a word or phrase to search for. A stem is the shared beginning of related words, so `garden` can also find words such as `gardener`.

## Install

Open Terminal. Go into this folder. The quotes matter because the folder name has spaces.

```bash
cd "/path/to/Concordance"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Leave the `.venv` folder where that command creates it. You only need to do these steps once.

## Start

From the same folder, with the environment still active:

```bash
python concordance.py
```

If you open a new Terminal window later, go into the folder again, run `source .venv/bin/activate`, and then run `python concordance.py`.

Quit the window before starting it again after a change, so the new copy loads.

## The window

The window has four sections.

**1. Documents.** Choose the corpus folder, which is the folder of documents to search. You can also choose an optional metadata file, a CSV that describes those documents. If you leave the metadata file blank, the tool reads every supported file in the corpus folder, including folders inside it. If you choose a metadata file, pick the column that contains each document’s file path, so each row is matched to its file. Group results by is optional. Choose a metadata column, such as organization, when you want counts split by that column.

**2. Search terms.** Choose the term list. Then choose one category, or All categories. Review word choices opens the word window for the category shown, with the ticks you have already saved, and does not start a search. Redo word choices for this category forgets the saved ticks for that one category. The term list file stays as it is.

**3. Options.** You can strip formatting marks and web addresses before searching. If your documents start with header lines such as `title:` and then a blank line, tick that box, click Find header fields, and tick the header fields that should be searched. The rest of each document is always searched. Flag documents shorter than a number of words marks those files in the results; use 0 to flag nothing. Language used for the counts uses only documents in the chosen language for the count files, while the matches list includes every language. All languages means every document is included in the counts. Also list words found near the terms adds the context report described below. It starts ticked.

**4. Results.** Choose a folder for the results. That folder must sit outside the corpus folder.

Run starts a search. Stop is grey until a run starts. While a run is going, Stop halts it at the next safe point and deletes that run’s unfinished folder. Saved word decisions are left as they were, including any you saved before you clicked Stop. When a run finishes, Open results folder opens the folder that was just written.

The status line under the buttons tells you what the tool is doing. Clicking empty space in the window moves the cursor out of a box you were typing in.

Your window choices are remembered when you close the tool. On a Mac they are saved in your Library folder, under Application Support, in a folder named Tool 4 Concordance. They are not saved inside the corpus.

You can make the text larger or smaller with Command-plus, Command-minus, and Command-zero. That choice is remembered.

## Word decisions

Before a search, the tool looks for other words that start with the same stem. A window lists those words when at least one of them has never been saved. Words with no saved decision yet are marked “new” and shown first. Words from your term list are marked “(from your term list)” and start ticked. Other words start unticked. A tick you saved earlier is used again.

Checked words are searched. Uncheck a word to leave it out. Save writes those ticks to a Decisions folder next to your term list, in a file named from that list, such as `example_terms_decisions.csv`. Cancel leaves the Decisions file unchanged. The term list itself is never changed.

The words that are actually searched are the words in your term list, plus any extra words you ticked, minus any term-list words you unticked.

If every word already has a saved decision, a run skips that window and keeps using the saved ticks. Review word choices can still open the window whenever you want to look again.

Each match can be marked in the keep column, and explained in the notes column, to record whether that use expresses the concept. You do this in `results.xlsx`. `yes` or `y` means the match is kept. `no` or `n` means it is not kept. A blank cell means it has not been coded yet. Any other word counts as unclear. Capital letters do not matter. For each category, the marks are copied from the most recent earlier run in the same results folder that included that category.

## A finished run

Each run creates a new folder inside your results folder. The name is the date, the time, and the category, such as `2026-10-01_14-30_Gardening`. Older runs are left as they are.

`results.xlsx` is an Excel workbook with one sheet for each table: Matches, Counts by category, Counts by group (when you chose a group column), Terms used, Word decisions, Context words (when that option is ticked), and Run settings. On every sheet the header row is bold and frozen, and the columns can be filtered.

On the Matches sheet the columns are in reading order. First is the column you chose under Group results by, when you chose one, then the date and the title when the metadata has those columns, then the term, the sentence, keep, and notes. After those come the category, the language, the short-document flag, where in the document the match was, the file name, and any other metadata. The discussion column, when the metadata has one, comes just before url, and url is the last column. The file path is left out of the workbook and kept in `matches.csv`. The sentence column is wide and wraps, keep and notes are moderately wide, and the other columns are narrow, so each row is only as tall as its sentence. Web addresses appear in full, as plain text.

The Run settings sheet has two columns, Setting and Value, with one setting on each row. Explanatory lines sit in the Setting column and leave Value blank. `run_settings.txt` is that same record in plain text, including, for each category, which earlier run its hand-coding marks came from and how many were carried forward.

The CSV files are the plain-text record of the same tables. They suit archiving and other software.

- `matches.csv` lists every matching sentence, in every language. It includes the file path, the category, the term, where in the document the sentence was found, the sentence itself, and the keep and notes marks.
- `counts_by_category.csv` counts matches, documents, and groups for each category. It also counts matches kept, not kept, not yet coded, and unclear.
- `counts_by_group.csv` is written when you chose a column under Group results by. It gives each group’s matches, its word count, and matches per 10,000 words, plus the same kept counts and kept matches per 10,000 words.
- `terms_used.csv` lists the terms that were actually searched.
- `word_decisions.csv` copies the saved word decisions for the categories in that run.
- `context_words.csv` is the context report, when that option is ticked.
- `run_settings.txt` records the choices used for that run, how many documents were read, any files that were missing, unreadable, or empty, and, for each category, which earlier run the hand-coding marks came from.

## The context report

When “Also list words found near the terms” is ticked, each category gets a list of words and two-word phrases that turn up unusually often in the same sentence as the terms that were searched. The score compares those sentences with the rest of the documents used for the counts. Common words such as “the” and “and” are left out, and so are the category’s own terms. A word must appear at least 5 times beside the terms. The list keeps up to 30 words and phrases, the ones most strongly tied to the terms.

`context_words.csv` has these columns: category, word or phrase, score, times with the terms, and times elsewhere. If a category has fewer than 10 sentences that contain its terms, that category gets one note instead of a list: “Too few sentences with these terms to find context words.”

If you untick the option, the run does not write `context_words.csv`. `run_settings.txt` says the list was skipped.

## What the tool will not change

The documents in the corpus folder are only read. The term list file is only read. Word ticks are stored in the Decisions folder beside the term list. Results are stored in the results folder you choose. The tool refuses to put the term list, the Decisions folder, or the results folder inside the corpus.

## License

Concordance is released under the MIT License. It was made by David Scott Warner.
