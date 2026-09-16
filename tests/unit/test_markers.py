from app.markers import split_markers


def test_a_subject_can_say_the_folder_and_the_tags():
    marked = split_markers("Deck plans $Backyard #diy #spring", "Some notes about it")
    assert marked.title == "Deck plans"
    assert marked.folder == "Backyard"
    assert marked.tags == ["diy", "spring"]
    assert marked.body == "Some notes about it"


def test_a_folder_name_with_spaces_is_quoted():
    assert split_markers('Paver notes $"Back yard project"').folder == "Back yard project"


def test_markers_can_sit_on_their_own_line_in_the_body():
    marked = split_markers("Edging for pavers", "non wood options\n\n$Backyard #diy\n")
    assert marked.folder == "Backyard"
    assert marked.tags == ["diy"]
    assert marked.body == "non wood options"


def test_ordinary_writing_is_left_alone():
    marked = split_markers("Sale today", "$5 off at Lowes this week #deal is in the text\nsecond line")
    assert marked.folder is None  # "$5" isn't a folder, and that line says more than the marker
    assert marked.tags == []
    assert marked.body == "$5 off at Lowes this week #deal is in the text\nsecond line"


def test_the_first_folder_wins_and_tags_add_up():
    marked = split_markers("Notes $One #a", "$Two #b\n")
    assert (marked.folder, marked.tags) == ("One", ["a", "b"])


def test_a_subject_that_is_only_markers_keeps_something_to_read():
    marked = split_markers("$Backyard #diy")
    assert marked.title == "" and marked.folder == "Backyard"  # the caller falls back to the original subject
