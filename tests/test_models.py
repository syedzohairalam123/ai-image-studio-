from app.extensions import db
from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image


def test_user_creation(db):
    """Test creating a user."""
    user = User(email="test@example.com", username="testuser")
    user.set_password("secret123")
    db.session.add(user)
    db.session.commit()

    assert user.id is not None
    assert user.check_password("secret123")
    assert not user.check_password("wrongpassword")
    assert user.to_dict()["email"] == "test@example.com"


def test_generation_model(db):
    """Test generation model."""
    user = User(email="gen@test.com", username="genuser")
    user.set_password("pass")
    db.session.add(user)
    db.session.commit()

    gen = Generation(
        user_id=user.id,
        prompt="a sunset over mountains",
        provider="stub",
        status="completed",
    )
    db.session.add(gen)
    db.session.commit()

    assert gen.id is not None
    assert gen.status == "completed"
    assert gen.user.username == "genuser"


def test_image_model(db):
    """Test image model."""
    user = User(email="img@test.com", username="imguser")
    user.set_password("pass")
    db.session.add(user)
    db.session.commit()

    gen = Generation(
        user_id=user.id,
        prompt="a cat",
        provider="stub",
        status="completed",
    )
    db.session.add(gen)
    db.session.commit()

    img = Image(
        generation_id=gen.id,
        user_id=user.id,
        filename="test.png",
        file_path="/uploads/test.png",
        width=512,
        height=512,
    )
    db.session.add(img)
    db.session.commit()

    assert img.id is not None
    assert img.generation.prompt == "a cat"
