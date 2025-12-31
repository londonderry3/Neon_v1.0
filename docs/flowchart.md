graph LR
    %% 0. External Actor
    User((User / Trader))

    %% 1. UI Layer
    subgraph UI_Layer [User interface layer]
        direction LR
        D1[Flowchart Viewer]
        D2[Project Context]
        D3[Logic Spec Editor]
        D4[Real-time Logs]
    end

    %% 2. Ingestion Layer
    subgraph Ingestion_Layer [1. Ingestion Layer]
        direction LR
        Market_Data[(Market Data API)]
        News_Stream[(News/RSS Stream)]
        Trend_Data[(Google Trends)]
    end

    %% 3. Analysis Layer
    subgraph Analysis_Layer [2. Analysis Layer]
        Engine[Core Orchestrator]
        
        subgraph Multi_Analysis [Multi-dimensional Analysis Model]
            direction LR
            M01[Trading Subject]
            M02[Macro-Economic]
            M03[Technical Analysis]
            M04[Keyword Trend]
            AI01[Jemi News Header]
            AI02[Jemi Deep Analysis]
        end
    end

    %% 4. Decision Layer
    subgraph Decision_Layer [3. Decision Layer]
        direction LR
        AI03[Dynamic Weight Tuner]
        Scoring{Hybrid Scoring Matrix}
    end

    %% 5. Report Layer
    subgraph Report_Layer [4. Report Layer]
        direction LR
        Telegram[Telegram Bot]
        Report[Streamlit Report]
    end

    %% Connections
    User <--> UI_Layer
    UI_Layer -.-> Engine
    Ingestion_Layer --> Engine
    Engine --> Multi_Analysis
    Multi_Analysis --> AI03
    AI03 --> Scoring
    Scoring --> Telegram
    Scoring --> Report

    %% Styling
    classDef default fill:#1a1b26,stroke:#4c566a,color:#eceff4,stroke-width:1px;
    classDef highlight fill:#24283b,stroke:#82aaff,color:#82aaff,stroke-width:2px;
    classDef domain fill:#1a1b26,stroke:#4c566a,stroke-dasharray: 5 5;
    classDef jemiNeon fill:#1a1b26,stroke:#ffff00,color:#ffff00,stroke-width:3px;
    classDef critical fill:#1a1b26,stroke:#f7768e,color:#f7768e,stroke-width:1px;

    class UI_Layer,Ingestion_Layer,Multi_Analysis domain;
    class Engine,Scoring highlight;
    class AI01,AI02,AI03,Decision_Layer jemiNeon;
    class Telegram,User critical;

