local questQuality = {
    WHITE = 1,
    GREEN = 2,
    BLUE = 3,
    PURPLE = 4,
    ORANGE = 5,
}

return {
    QUEST_STATE = {
        IDLE = 1,
        COMPLETED = 2,
        FIGHTING = 3,
    },
    QUEST_TYPE = {
        SLG_MONSTER = 1,
        RESCUE_SURVIVORS = 2,
        RPG_STAGE = 3,
        FIRE_CRYSTAL_LEAK = 11,
        VENTURE = 100,
    },
    QUEST_QUALITY = questQuality,
    QUEST_PLOT_TYPE = {
        FIRST_CLICK_QUEST = 1,
    },
    QUEST_TAG = {
        EXPERT = 1,
    },
    QUEST_QUALITY_BORN_EFFECT = {
        [questQuality.WHITE] = "fxui_intelligence_white_lxy",
        [questQuality.GREEN] = "fxui_intelligence_green_lxy",
        [questQuality.BLUE] = "fxui_intelligence_blue_lxy",
        [questQuality.PURPLE] = "fxui_intelligence_purple_lxy",
        [questQuality.ORANGE] = "fxui_intelligence_orange_lxy",
    },
}
