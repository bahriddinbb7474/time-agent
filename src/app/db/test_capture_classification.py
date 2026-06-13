from app.services.capture_router_service import (
    CAPTURE_KIND_BOSS,
    CAPTURE_KIND_IGNORE,
    CAPTURE_KIND_LATER,
    CAPTURE_KIND_TASK,
    CaptureRouterService,
)


def main():
    service = CaptureRouterService()

    assert service.classify_text("/today").kind == CAPTURE_KIND_IGNORE
    assert service.classify_text("   ").kind == CAPTURE_KIND_IGNORE

    later = service.classify_text("Купить книгу без срока")
    assert later.kind == CAPTURE_KIND_LATER
    assert later.text == "Купить книгу без срока"

    timed = service.classify_text("work Встреча завтра 14:00 40")
    assert timed.kind == CAPTURE_KIND_TASK
    assert timed.category == "work"
    assert timed.title == "Встреча"
    assert timed.planned_at is not None
    assert timed.duration_min == 40

    category_only = service.classify_text("health Витамины")
    assert category_only.kind == CAPTURE_KIND_TASK
    assert category_only.category == "health"

    urgent = service.classify_text("Срочно проверить договор")
    assert urgent.kind == CAPTURE_KIND_BOSS
    assert urgent.category == "work"

    boss = service.classify_text("Шеф: отправить отчет")
    assert boss.kind == CAPTURE_KIND_BOSS

    print("PASS: capture classification is pure and writes no DB")


if __name__ == "__main__":
    main()
