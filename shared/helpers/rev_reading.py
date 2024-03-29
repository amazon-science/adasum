from shared.helpers.io import parse_gz
from zipfile import ZipFile
from shared.constants.general import SRC, TGT
from shared.helpers.cleaning import clean_rev_text
from shared.constants.amazon import REVIEW_TEXT as AMA_REVIEW_TEXT, \
    REVIEW_TITLE as AMA_REVIEW_TITLE, HELPFUL as AMA_HELPFUL, \
    VERIFIED as AMA_VERIFIED, ASIN as AMA_ASIN, REVIEWER_ID as AMA_REVIEWER_ID,\
    OVERALL as AMA_RATING
from shared.constants.yelp import REVIEW_TEXT as YELP_REVIEW_TEXT, \
    BUSINESS_ID as YELP_BUSINESS_ID, REVIEW_ID as YELP_REVIEW_ID,\
    RATING as YELP_RATING
from shared.helpers.general import is_in_range
from shared.helpers.io import read_table_data
from collections import defaultdict
import os
import json


def iter_fewsum_revs(input_data_path, dataset='amazon'):
    """"Iterates over reviews in a FewSum file."""
    counter = 0

    if dataset == "amazon":
        entity_id_fname = AMA_ASIN
        review_text = AMA_REVIEW_TEXT
        reviewer_id = AMA_REVIEWER_ID
    else:
        entity_id_fname = YELP_BUSINESS_ID
        review_text = YELP_REVIEW_TEXT
        reviewer_id = YELP_REVIEW_ID

    with ZipFile(input_data_path, 'r') as zip:
        file_names = sorted(zip.namelist())
        for file_name in file_names:
            if file_name.split(".")[-1] != "csv":
                continue
            with zip.open(file_name) as f:
                data = read_table_data(f)
                for indx, entry in data.iterrows():
                    new_entry = {}
                    counter += 1
                    new_entry[entity_id_fname] = entry['group_id'].split("_")[0]
                    new_entry[review_text] = entry['review_text']
                    new_entry[reviewer_id] = counter
                    yield new_entry


def iter_ama_revs(input_data_path, clean_text=False, verified_only=False):
    """Yields reviews from a .gz file. Optionally cleans the text.

    Args:
        input_data_path: .gz file with reviews.
        clean_text: whether to clean text.
        verified_only: if set to ``True``, it will yield only verified reviews.
    """
    assert os.path.isfile(input_data_path)
    assert input_data_path.split(".")[-1] == 'gz'
    dupl_tracker = defaultdict(lambda: {AMA_REVIEWER_ID: set(),
                                        AMA_REVIEW_TEXT: set()})
    for rev in parse_gz(input_data_path):
        if AMA_REVIEW_TEXT not in rev:
            continue
        if verified_only and not rev[AMA_VERIFIED]:
            continue

        reviewer_id = rev[AMA_REVIEWER_ID]
        asin = rev[AMA_ASIN]

        # skipping duplicates
        if reviewer_id in dupl_tracker[asin][AMA_REVIEWER_ID]:
            continue
        if rev[AMA_REVIEW_TEXT] in dupl_tracker[asin][AMA_REVIEW_TEXT]:
            continue

        dupl_tracker[asin][AMA_REVIEWER_ID].add(reviewer_id)
        dupl_tracker[asin][AMA_REVIEW_TEXT].add(rev[AMA_REVIEW_TEXT])

        rev[AMA_HELPFUL] = int((rev[AMA_HELPFUL].replace(",", ""))) \
            if AMA_HELPFUL in rev else 0
        if clean_text:
            # text cleaning
            if AMA_REVIEW_TITLE in rev:
                rev[AMA_REVIEW_TITLE] = clean_rev_text(rev[AMA_REVIEW_TITLE])
            rev[AMA_REVIEW_TEXT] = clean_rev_text(rev[AMA_REVIEW_TEXT])
        yield rev


def iter_yelp_revs(input_data_path,  clean_text=True):
    """Yields reviews. Optionally cleans the text.

    Args:
        input_data_path: .gz file with reviews.
        clean_text: whether to clean text.
    """
    assert os.path.isfile(input_data_path)
    with open(input_data_path, encoding='utf-8') as f:
        for line in f:
            rev = json.loads(line)
            if clean_text:
                rev[YELP_REVIEW_TEXT] = clean_rev_text(rev[YELP_REVIEW_TEXT],
                                                       remove_new_lines=True,
                                                       rpl_multi_space=True)
            yield rev


def read_amazon_revs(input_file_paths, src_rev_min_len=None,
                     src_rev_max_len=None, tgt_rev_min_len=None,
                     tgt_rev_max_len=None, verified=False, limit=None,
                     tokenizer=None):
    """Reads Amazon reviews from the .gz files or .zip (FewSum).

    Returns:
        dict ASINs mapped to source and target reviews.
     """
    if isinstance(input_file_paths, str):
        input_file_paths = [input_file_paths]
    tok = lambda x: (tokenizer(x) if tokenizer is not None else x.split())
    # ASINs mapped to source and target reviews
    coll = defaultdict(lambda: {SRC: [], TGT: []})

    dupl_tracker = defaultdict(lambda: {AMA_REVIEWER_ID: set(),
                                        AMA_REVIEW_TEXT: set()})

    review_count = 0
    for input_file_path in input_file_paths:

        # reading and filtering
        if input_file_path.split(".")[-1] == "zip":
            ama_iter = iter_fewsum_revs(input_file_path, dataset='amazon')
        else:
            ama_iter = iter_ama_revs(input_file_path, verified_only=verified,
                                     clean_text=True)

        for indx, rev in enumerate(ama_iter):
            if limit is not None and review_count >= limit:
                break

            asin = rev[AMA_ASIN]
            rev_text = rev[AMA_REVIEW_TEXT]
            ntokens = len(tok(rev_text))

            reviewer_id = rev[AMA_REVIEWER_ID]

            # skipping duplicates
            if reviewer_id in dupl_tracker[asin][AMA_REVIEWER_ID]:
                continue
            if rev[AMA_REVIEW_TEXT] in dupl_tracker[asin][AMA_REVIEW_TEXT]:
                continue

            dupl_tracker[asin][AMA_REVIEWER_ID].add(reviewer_id)
            dupl_tracker[asin][AMA_REVIEW_TEXT].add(rev[AMA_REVIEW_TEXT])

            if is_in_range(ntokens, min=src_rev_min_len,
                           max=src_rev_max_len):
                coll[asin][SRC].append((indx, rev))

            if is_in_range(ntokens, min=tgt_rev_min_len,
                           max=tgt_rev_max_len):
                coll[asin][TGT].append((indx, rev))

            review_count += 1

    return coll


def read_yelp_revs(input_file_path, src_rev_min_len=None,
                   src_rev_max_len=None, tgt_rev_min_len=None,
                   tgt_rev_max_len=None, limit=None, tokenizer=None):
    """Reads YELP reviews."""
    tok = lambda x: (tokenizer(x) if tokenizer is not None else x.split())
    coll = defaultdict(lambda: {SRC: [], TGT: []})

    buss_to_text = defaultdict(lambda: set())

    # reading and filtering
    if input_file_path.split(".")[-1] == "zip":
        rev_iter = iter_fewsum_revs(input_file_path, dataset='yelp')
    else:
        rev_iter = iter_yelp_revs(input_file_path, clean_text=True)

    review_count = 0

    for (indx, rev) in enumerate(rev_iter):

        if limit is not None and review_count >= limit:
            break

        bus_id = rev[YELP_BUSINESS_ID]
        rev_text = rev[YELP_REVIEW_TEXT]
        rev_text_words = tok(rev_text)

        # standartization
        rev[AMA_REVIEW_TEXT] = rev_text
        # rev[AMA_RATING] = rev[YELP_RATING]

        # avoiding duplicates
        if rev_text in buss_to_text[bus_id]:
            continue

        if is_in_range(len(rev_text_words), min=src_rev_min_len,
                       max=src_rev_max_len):
            coll[bus_id][SRC].append((indx, rev))

        if is_in_range(len(rev_text_words), min=tgt_rev_min_len,
                       max=tgt_rev_max_len):
            coll[bus_id][TGT].append((indx, rev))

        buss_to_text[bus_id].add(rev_text)
        review_count += 1

    return coll
