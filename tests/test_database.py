from actup.models import GitHubAction


def test_save_popular_action(test_db):
    """Test saving a popular action."""
    action = GitHubAction(name="actions/checkout", owner="actions", repo="checkout", latest_major_version="v4")
    test_db.save_popular_action(action)

    actions = test_db.get_popular_actions()
    assert len(actions) == 1
    assert actions[0].name == "actions/checkout"
    assert actions[0].latest_major_version == "v4"
