import pytest

from app.modules.metadata.domain.source_name import metadata_from_source_name


@pytest.mark.parametrize(
    "name,directory,title,author,index",
    [
        ("三体 - 刘慈欣.epub", False, "三体", "刘慈欣", None),
        ("《三体》作者：刘慈欣.pdf", False, "三体", "刘慈欣", None),
        ("三体 [作者：刘慈欣]", True, "三体", "刘慈欣", None),
        ("三体 第二卷 - 刘慈欣.epub", False, "三体", "刘慈欣", 2),
        (
            "Title - Subtitle - Author.epub",
            False,
            "Title",
            "Subtitle",
            None,
        ),
        ("science-fiction.txt", False, "science", "fiction", None),
        ("Some.name", True, "Some.name", None, None),
        ("三体", True, "三体", None, None),
        ("[海贼王][尾田荣一郎].cbz", False, "海贼王", "尾田荣一郎", None),
        ("[海贼王][尾田荣一郎].CBR", False, "海贼王", "尾田荣一郎", None),
        ("[海贼王][尾田荣一郎]", True, "海贼王", "尾田荣一郎", None),
        (" [ 海贼王 ] [ 尾田荣一郎 ] .zip", False, "海贼王", "尾田荣一郎", None),
        ("[海贼王 第二卷][尾田荣一郎].cbz", False, "海贼王", "尾田荣一郎", 2),
        ("[Book.name][Author]", True, "Book.name", "Author", None),
        ("[Book][]", True, "[Book][]", None, None),
        ("[ ][Author]", True, "[ ][Author]", None, None),
        ("[Book][Author][Group]", True, "Book", "Author", None),
        ("[Book][Author", True, "[Book][Author", None, None),
    ],
)
def test_source_name(name, directory, title, author, index):
    result = metadata_from_source_name(name, is_directory=directory)
    assert (result.title, result.author, result.volume_index) == (title, author, index)


@pytest.mark.parametrize("directory", [True, False])
@pytest.mark.parametrize("name,title,author", [
    ("[在超市后门吸烟的二人][地主][Vol.01-Vol.07][东立][电子版]", "在超市后门吸烟的二人", "地主"),
    ("书名（作者）", "书名", "作者"),
    ("《书名》作者", "书名", "作者"),
    ("[Spider-Man][Stan Lee]", "Spider-Man", "Stan Lee"),
    ("Spider-Man", "Spider", "Man"),
    ("书名（修订版）", "书名", "修订版"),
    ("The Long Goodbye", "The Long Goodbye", None),
    ("[Spider-Man]", "Spider-Man", None),
    ("[书名][]", "[书名][]", None),
    ("[书名][作者", "[书名][作者", None),
    ("[书名 Vol.02", "[书名 Vol.02", None),
    ("书名-作者[附加)", "书名-作者[附加)", None),
    ("[书名（副标题）][作者]", "书名（副标题）", "作者"),
    ("[书名（）][作者]", "[书名（）][作者]", None),
    ("书名 [作者：张三][电子版]", "书名", "张三"),
    ("[Spider-Man 作者：Stan Lee]", "Spider-Man", "Stan Lee"),
    ("Spider-Man Author: Stan Lee - Edition", "Spider-Man", "Stan Lee"),
    ("《书名》AUTHOR：张三", "书名", "张三"),
    ("书名【author: Anne-Marie & Bob 著】[版本]", "书名", "Anne-Marie & Bob 著"),
    ("书名-副标题 作者：张三", "书名-副标题", "张三"),
    ("书名:副标题", "书名:副标题", None),
    ("书名/副标题", "书名/副标题", None),
    ("作者：张三", "作者：张三", None),
    ("书名 -- __ ｜ 作者 - 附加", "书名", "作者"),
])
def test_general_source_name(name, title, author, directory):
    source = name if directory else name + ".CBZ"
    result = metadata_from_source_name(source, is_directory=directory)
    assert (result.title, result.author) == (title, author)


@pytest.mark.parametrize("separator", list("-－–—_＿|｜"))
def test_each_top_level_separator(separator):
    result = metadata_from_source_name(f"书名{separator}作者{separator}版本", is_directory=True)
    assert (result.title, result.author) == ("书名", "作者")


@pytest.mark.parametrize("opening,closing", list(zip("[［【(（《〈", "]］】)）》〉", strict=True)))
def test_each_bracket_pair(opening, closing):
    result = metadata_from_source_name(f"{opening}书名{closing}{opening}作者{closing}", is_directory=True)
    assert (result.title, result.author) == ("书名", "作者")
