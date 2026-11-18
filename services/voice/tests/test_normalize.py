from app.recognizer import normalize


def test_seven_spelling_variant_preserves_promotion_coordinates():
    assert normalize("Tốt e bẩy tới e tám phong cấp thành hậu.") == (
        "tốt e bảy tới e tám phong cấp thành hậu"
    )
    assert normalize("Tốt E7 tới E8 phong cấp thành hậu.") == (
        "tốt e bảy tới e tám phong cấp thành hậu"
    )


def test_normalization_keeps_misheard_pieces_conflicts_and_negation():
    for text in [
        "tốn e bảy tới e tám phong cấp thành hậu",
        "tốt e bảy tới e tám phong tịnh hậu",
        "đừng đi tốt e bảy tới e tám phong cấp thành hậu",
        "tốt từ cột hai hàng hai đến cột hai hàng vốn",
    ]:
        assert normalize(text) == text
