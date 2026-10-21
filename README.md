# Concordance

Concordance is a dictionary-based keyword-in-context tool for content analysis. Given a corpus of documents and a coding dictionary of terms grouped into categories, it retrieves every occurrence of each term in its sentence, traces each to its document and metadata, produces frequency counts by category and by document group, and records every analytic decision so the analysis can be reproduced and audited.

It reads the documents. It does not change them. It also does not add to, remove from, or rewrite your term list.

## What you need

- Python 3. It was tested on a Mac with Python 3.14.2 and should work with other recent versions of Python 3, but it has not been tested on Windows or Linux. The python.org installer includes the window system this tool uses.
- A folder of documents. The tool can read `.txt`, `.md`, `.docx`, `.pdf`, `.html`, and `.htm` files.
- A term list. This is a spreadsheet saved as CSV, with columns named `category`, `term`, and `stem`. `example_terms.csv` in this folder is a small made-up list you can copy. A category is a topic, such as Gardening. A term is a word or phrase to search for. A stem is the shared beginning of related words, so `garden` can also find words such as `gardener`. You can add an optional fourth column named `definition`. The first definition filled in for a category is shown under the title of the word window, in gray, and is copied into the category counts. A term list without that column works as before.

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

**2. Search terms.** Choose the term list. Under it, you can choose an optional exclusion list. That file is a CSV with two columns, `category` and `phrase`. `example_exclusions.csv` is a small made-up list in the same style. A blank category means the phrase applies to every category. Phrases are matched in the same way as terms: capital letters do not matter, a hyphen and a space are treated as the same, and only whole words match. When a term match falls inside one of those phrases for its category, it is not counted. It is listed instead in `excluded_matches.csv` and on the Excluded sheet, with the phrase that excluded it. The exclusion list is only read. Then choose one category, or All categories. Review word choices opens the word window for the category shown, with the ticks you have already saved, and does not start a search. The term list file stays as it is.

**3. Options.** You can strip formatting marks and web addresses before searching. If your documents start with header lines such as `title:` and then a blank line, tick that box, click Find header fields, and tick the header fields that should be searched. The rest of each document is always searched. Flag documents shorter than a number of words marks those files in the results; use 0 to flag nothing. Language used for the counts uses only documents in the chosen language for the count files, while the matches list includes every language. All languages means every document is included in the counts, except a document that has only header lines and no body text. Those are labeled No body and left out of the counts, because they have no proposal text. Coding sample size per category chooses how many counted matches to code by hand in each category. It starts at 100. Use 0 to put every counted match in the sample. Sample seed starts at 1. The same seed draws the same sample again. Also list words found near the terms adds the context report described below. It starts ticked.

**4. Results.** Choose a folder for the results. That folder must sit outside the corpus folder.

Run starts a search. Stop is grey until a run starts. While a run is going, Stop halts it at the next safe point and deletes that run’s unfinished folder. Saved word decisions are left as they were, including any you saved before you clicked Stop. When a run finishes, Open results folder opens the folder that was just written.

The status line under the buttons tells you what the tool is doing. Clicking empty space in the window moves the cursor out of a box you were typing in.

Your window choices are remembered when you close the tool. On a Mac they are saved in your Library folder, under Application Support, in a folder named Tool 4 Concordance. They are not saved inside the corpus.

You can make the text larger or smaller with Command-plus, Command-minus, and Command-zero. That choice is remembered.

## Word decisions

Before a search, the tool looks for other words that start with the same stem. A window lists those words when at least one of them has never been saved. The title shows the category name in lowercase, such as “Words for credible neutrality”. That lowercase form is only for display. Saved decisions, result files, and folder names keep the category name as it is written in the term list. If the category has a definition, it appears in gray just under that title. In the top corner, during a run, the window shows which category this is out of how many will open the window in this run, such as “Category 3 of 17”. Categories whose words are already decided are not included in that count. Review word choices opens one category on its own and does not show that counter. Words with no saved decision yet are marked “new” and shown first. Words from your term list are marked “(from your term list)” and start ticked. Other words start unticked. A tick you saved earlier is used again.

Checked words are searched. Uncheck a word to leave it out. Save writes those ticks to a Decisions folder next to your term list, in a file named from that list, such as `example_terms_decisions.csv`. Cancel leaves the Decisions file unchanged. The term list itself is never changed.

The words that are actually searched are the words in your term list, plus any extra words you ticked, minus any term-list words you unticked.

If every word already has a saved decision, a run skips that window and keeps using the saved ticks. Review word choices can still open the window whenever you want to look again.

Each match can be marked in the code column, and explained in the notes column, to record how that use relates to the concept. You do this in `results.xlsx`. The code column is a dropdown with four marks: Value, Descriptive, Wrong sense, and Unclear. A blank cell means it has not been coded yet. Capital letters and extra spaces do not matter. Any other value is listed in Run settings as an unrecognized mark, with the file name and the term, and is counted as uncoded. Marks in an older keep column are read in the same way. For each category, the marks are copied from the most recent earlier run in the same results folder that included that category.

The coding sample tells you which of those matches to code. It is drawn from the matches included in the counts, after exclusion phrases and the language choice. Matches in other languages stay in the matches list and are marked `no` in `in_sample`. For each category, if there are no more counted matches than the sample size, every one of them is in the sample. Otherwise the tool gives each match a stable random number from the sample seed, the file, the category, the term, and its position in the document, and keeps the matches with the lowest numbers, exactly as many as the sample size. Running again with the same seed draws the same sample. Adding or removing a few matches changes the sample only for the matches whose numbers fall among the lowest. A sample size of 0 skips that draw and puts every counted match in the sample.

In the category counts, `sample_size` is how many matches were put in the sample, and `sample_coded` is how many of those are marked Value, Descriptive, or Wrong sense. `share_value` is the Value marks divided by those three, among the sample only. Unclear is left out of that division and is reported only as a count. `share_value_low` and `share_value_high` are a 95% Wilson confidence interval around that share: a range that is likely to contain the share you would see if you coded the whole category in the same way. `estimated_value` multiplies `share_value` by the category’s full match count, which estimates how many matches would be marked Value if every match were coded like the sample. Those four estimate cells are left blank when none of the sampled matches is marked Value, Descriptive, or Wrong sense. The group counts do not include these estimates.

## A finished run

Each run creates a new folder inside your results folder. The name is the date, the time, and the category, such as `2026-10-01_14-30_Gardening`. Older runs are left as they are.

`results.xlsx` is an Excel workbook with one sheet for each table: Matches, Excluded, Counts by category, Counts by group (when you chose a group column), Terms used, Word decisions, Context words (when that option is ticked), and Run settings. On every sheet the header row is bold and frozen, and the columns can be filtered.

On the Matches sheet the columns are in reading order. First is the column you chose under Group results by, when you chose one, then the date and the title when the metadata has those columns, then the term, the sentence, in_sample, code, and notes. `in_sample` is `yes` or `no`. Within each category, the sampled rows are listed first. After those come the category, the language, the short-document flag, where in the document the match was, the file name, and any other metadata. The discussion column, when the metadata has one, comes just before url, and url is the last column. The file path is left out of the workbook and kept in `matches.csv`. The sentence column is wide and wraps, code and notes are moderately wide, and the other columns are narrow, so each row is only as tall as its sentence. Documents with no body text are labeled No body in the language column. Web addresses appear in full, as plain text.

The Run settings sheet has two columns, Setting and Value, with one setting on each row. Explanatory lines sit in the Setting column and leave Value blank. `run_settings.txt` is that same record in plain text, including, for each category, which earlier run its hand-coding marks came from and how many were carried forward. It also names the exclusion list, or says none, and records how many matches each phrase excluded. It records the coding sample size, the sample seed, and how the sample was drawn.

The CSV files are the plain-text record of the same tables. They suit archiving and other software.

- `matches.csv` lists every matching sentence, in every language, with sampled rows first within each category. It includes the file path, the category, the term, where in the document the sentence was found, the sentence itself, whether the row is in the coding sample, and the code and notes marks. Matches that fell inside an exclusion phrase are left out of this file.
- `excluded_matches.csv` lists those left-out matches, in every language, with the phrase that excluded each one.
- `counts_by_category.csv` counts matches, documents, and groups for each category. It includes the category definition when the term list has one. It also counts matches marked Value, Descriptive, Wrong sense, not yet coded, and Unclear, and how many matches were excluded. The excluded count uses the same language as the other counts. It adds the coding-sample size, how many sampled matches are marked Value, Descriptive, or Wrong sense, the share marked Value, the low and high ends of the 95% Wilson interval, and the estimated number marked Value. Those last four are blank when none of the sample is marked Value, Descriptive, or Wrong sense.
- `counts_by_group.csv` is written when you chose a column under Group results by. It gives each group’s matches, its word count, and matches per 10,000 words, plus the same four code counts, Value matches per 10,000 words, and how many matches were excluded. It does not include the sample estimates.
- `terms_used.csv` lists the terms that were actually searched.
- `word_decisions.csv` copies the saved word decisions for the categories in that run.
- `context_words.csv` is the context report, when that option is ticked.
- `run_settings.txt` records the choices used for that run, how many documents were read, any files that were missing, unreadable, or empty, the exclusion list and how many matches each phrase excluded, the coding sample size, the sample seed, how the sample was drawn, and, for each category, which earlier run the hand-coding marks came from.

## The context report

When “Also list words found near the terms” is ticked, each category gets a list of words and two-word phrases that turn up unusually often in the same sentence as the terms that were searched. The score compares those sentences with the rest of the documents used for the counts. Common words such as “the” and “and” are left out, and so are the category’s own terms. A word must appear at least 5 times beside the terms. The list keeps up to 30 words and phrases, the ones most strongly tied to the terms.

`context_words.csv` has these columns: category, word or phrase, score, times with the terms, and times elsewhere. If a category has fewer than 10 sentences that contain its terms, that category gets one note instead of a list: “Too few sentences with these terms to find context words.”

If you untick the option, the run does not write `context_words.csv`. `run_settings.txt` says the list was skipped.

## What the tool will not change

The documents in the corpus folder are only read. The term list file is only read. The exclusion list, when you choose one, is only read. Word ticks are stored in the Decisions folder beside the term list. Results are stored in the results folder you choose. The tool refuses to put the term list, the Decisions folder, or the results folder inside the corpus.

## License

Concordance is released under the MIT License. It was made by David Scott Warner.
