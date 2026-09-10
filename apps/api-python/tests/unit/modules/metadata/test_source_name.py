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
            "Title - Subtitle - Author",
            None,
            None,
        ),
        ("science-fiction.txt", False, "science-fiction", None, None),
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
        ("[Book][Author][Group]", True, "[Book][Author][Group]", None, None),
        ("[Book][Author", True, "[Book][Author", None, None),
    ],
)
def test_source_name(name, directory, title, author, index):
    result = metadata_from_source_name(name, is_directory=directory)
    assert (result.title, result.author, result.volume_index) == (title, author, index)
