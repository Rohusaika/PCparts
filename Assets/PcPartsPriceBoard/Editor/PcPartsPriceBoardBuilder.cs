#if UNITY_EDITOR
using System.IO;
using TMPro;
using UdonSharpEditor;
using UnityEditor;
using UnityEditor.Events;
using UnityEngine;
using UnityEngine.UI;
using VRC.SDK3.Components;
using VRC.SDKBase;
using VRC.Udon;

public class PcPartsPriceBoardBuilder : EditorWindow
{
    private TMP_FontAsset _japaneseFont;
    private string _jsonUrl = "https://YOUR_NAME.github.io/YOUR_REPOSITORY/prices.json";
    private float _worldWidthMeters = 3.2f;

    private static readonly Color Background = new Color(0.025f, 0.035f, 0.055f, 0.98f);
    private static readonly Color Panel = new Color(0.07f, 0.09f, 0.13f, 0.96f);
    private static readonly Color PanelAlt = new Color(0.095f, 0.12f, 0.17f, 0.96f);
    private static readonly Color Accent = new Color(0.20f, 0.65f, 1.0f, 1f);
    private static readonly Color TextMain = new Color(0.94f, 0.97f, 1f, 1f);
    private static readonly Color TextSub = new Color(0.66f, 0.73f, 0.82f, 1f);

    [MenuItem("Tools/PC Parts Price Board/Build 16:9 Prefab")]
    public static void OpenWindow()
    {
        GetWindow<PcPartsPriceBoardBuilder>("PC Parts Board");
    }

    private void OnGUI()
    {
        EditorGUILayout.LabelField("VRChat PC Parts Price Board", EditorStyles.boldLabel);
        EditorGUILayout.Space(6);
        _japaneseFont = (TMP_FontAsset)EditorGUILayout.ObjectField("Japanese TMP Font", _japaneseFont, typeof(TMP_FontAsset), false);
        _jsonUrl = EditorGUILayout.TextField("Remote JSON URL", _jsonUrl);
        _worldWidthMeters = EditorGUILayout.Slider("World Width (m)", _worldWidthMeters, 1.6f, 6.4f);

        EditorGUILayout.HelpBox(
            "Japanese font files are not bundled. Select a TMP Font Asset containing Japanese glyphs. " +
            "For VRChat trusted loading, host prices.json on *.github.io, gist.githubusercontent.com, Pastebin, Disbridge, or VRCDN.",
            MessageType.Info);

        EditorGUILayout.Space(8);
        if (GUILayout.Button("Build Prefab", GUILayout.Height(36))) BuildPrefab();
    }

    private void BuildPrefab()
    {
        const string folder = "Assets/PcPartsPriceBoard/Prefabs";
        if (!AssetDatabase.IsValidFolder("Assets/PcPartsPriceBoard")) AssetDatabase.CreateFolder("Assets", "PcPartsPriceBoard");
        if (!AssetDatabase.IsValidFolder(folder)) AssetDatabase.CreateFolder("Assets/PcPartsPriceBoard", "Prefabs");

        GameObject root = new GameObject("PcPartsPriceBoard_16x9", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
        RectTransform rootRect = root.GetComponent<RectTransform>();
        rootRect.sizeDelta = new Vector2(1600f, 900f);
        root.transform.localScale = Vector3.one * (_worldWidthMeters / 1600f);

        Canvas canvas = root.GetComponent<Canvas>();
        canvas.renderMode = RenderMode.WorldSpace;
        canvas.sortingOrder = 10;
        root.AddComponent<VRCUiShape>();

        CanvasScaler scaler = root.GetComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPixelSize;
        scaler.scaleFactor = 1f;
        scaler.referencePixelsPerUnit = 100f;

        Image bg = root.AddComponent<Image>();
        bg.color = Background;
        bg.raycastTarget = false;

        PcPartsPriceBoard board = root.AddUdonSharpComponent<PcPartsPriceBoard>();
        board.dataUrl = string.IsNullOrWhiteSpace(_jsonUrl) ? VRCUrl.Empty : new VRCUrl(_jsonUrl.Trim());
        board.itemsPerPage = 56;
        board.maximumItems = 512;

        TMP_Text title = CreateText(root.transform, "Title", "PC PARTS PRICE BOARD", 42, FontStyles.Bold, TextAlignmentOptions.Left, TextMain, 38, 20, 690, 52);
        TMP_Text updated = CreateText(root.transform, "Updated", "更新: 未取得", 22, FontStyles.Normal, TextAlignmentOptions.Right, TextSub, 900, 22, 660, 32);
        TMP_Text source = CreateText(root.transform, "Source", "参照: 価格.com 最安値（指定店舗のみ）", 18, FontStyles.Normal, TextAlignmentOptions.Right, TextSub, 760, 58, 800, 28);
        TMP_Text status = CreateText(root.transform, "Status", "価格データを待機中", 18, FontStyles.Normal, TextAlignmentOptions.Left, TextSub, 40, 67, 650, 28);

        board.titleText = title;
        board.updatedText = updated;
        board.sourceText = source;
        board.statusText = status;

        string[] tabLabels = { "CPU", "GPU", "DDR4", "DDR5", "SSD", "HDD" };
        string[] tabEvents = { "TabCPU", "TabGPU", "TabDDR4", "TabDDR5", "TabSSD", "TabHDD" };
        UdonBehaviour backing = root.GetComponent<UdonBehaviour>();

        float tabX = 40f;
        for (int i = 0; i < tabLabels.Length; i++)
        {
            Button tab = CreateButton(root.transform, "Tab_" + tabLabels[i], tabLabels[i], tabX, 108, 240, 48, PanelAlt, 24);
            Bind(tab, backing, tabEvents[i]);
            tabX += 252f;
        }

        TMP_Text category = CreateText(root.transform, "Category", "CPU", 28, FontStyles.Bold, TextAlignmentOptions.Left, TextMain, 40, 170, 280, 40);
        Button groupPrev = CreateButton(root.transform, "GroupPrevious", "‹", 330, 168, 64, 42, PanelAlt, 32);
        TMP_Text group = CreateText(root.transform, "Group", "‹  すべて  ›", 24, FontStyles.Bold, TextAlignmentOptions.Center, Accent, 402, 168, 430, 42);
        Button groupNext = CreateButton(root.transform, "GroupNext", "›", 840, 168, 64, 42, PanelAlt, 32);
        TMP_Text page = CreateText(root.transform, "Page", "0 / 0", 22, FontStyles.Bold, TextAlignmentOptions.Right, TextSub, 1320, 174, 240, 32);

        board.categoryText = category;
        board.groupText = group;
        board.pageText = page;
        Bind(groupPrev, backing, "PreviousGroup");
        Bind(groupNext, backing, "NextGroup");

        const int columns = 4;
        const int rows = 14;
        const int slots = columns * rows;
        GameObject[] rowObjects = new GameObject[slots];
        TMP_Text[] nameTexts = new TMP_Text[slots];
        TMP_Text[] priceTexts = new TMP_Text[slots];
        TMP_Text[] arrowTexts = new TMP_Text[slots];

        float contentX = 40f;
        float contentY = 222f;
        float columnWidth = 370f;
        float columnGap = 16f;
        float rowHeight = 42f;
        float rowGap = 2f;

        int slot = 0;
        for (int col = 0; col < columns; col++)
        {
            float x = contentX + col * (columnWidth + columnGap);
            for (int row = 0; row < rows; row++)
            {
                float y = contentY + row * (rowHeight + rowGap);
                GameObject rowGo = CreatePanel(root.transform, "Row_" + slot.ToString("00"), x, y, columnWidth, rowHeight, row % 2 == 0 ? Panel : PanelAlt);
                rowObjects[slot] = rowGo;
                nameTexts[slot] = CreateText(rowGo.transform, "Name", "Intel Core i7-13700K", 17, FontStyles.Normal, TextAlignmentOptions.Left, TextMain, 10, 4, 226, 34);
                priceTexts[slot] = CreateText(rowGo.transform, "Price", "44,000円", 17, FontStyles.Bold, TextAlignmentOptions.Right, TextMain, 232, 4, 102, 34);
                arrowTexts[slot] = CreateText(rowGo.transform, "Arrow", "↓", 25, FontStyles.Bold, TextAlignmentOptions.Center, new Color(0.25f, 0.64f, 1f, 1f), 336, 2, 32, 38);
                slot++;
            }
        }

        board.rowObjects = rowObjects;
        board.nameTexts = nameTexts;
        board.priceTexts = priceTexts;
        board.arrowTexts = arrowTexts;

        Button prevPage = CreateButton(root.transform, "PreviousPage", "‹ 前ページ", 520, 847, 220, 42, PanelAlt, 22);
        Button refresh = CreateButton(root.transform, "Refresh", "更新", 760, 847, 120, 42, Accent, 22);
        Button nextPage = CreateButton(root.transform, "NextPage", "次ページ ›", 900, 847, 220, 42, PanelAlt, 22);
        Bind(prevPage, backing, "PreviousPage");
        Bind(refresh, backing, "Refresh");
        Bind(nextPage, backing, "NextPage");

        TMP_Text note = CreateText(root.transform, "Note", "↑ 値上がり / ↓ 値下がり / → 同額・前日データなし　　※ 前回値を使用", 16, FontStyles.Normal, TextAlignmentOptions.Left, TextSub, 40, 855, 460, 28);

        board.ApplyProxyModifications();
        ApplyFont(root);

        string prefabPath = folder + "/PcPartsPriceBoard_16x9.prefab";
        PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
        DestroyImmediate(root);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Selection.activeObject = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        EditorGUIUtility.PingObject(Selection.activeObject);
        Debug.Log("Created: " + prefabPath);
    }

    private void ApplyFont(GameObject root)
    {
        if (_japaneseFont == null) return;
        TMP_Text[] texts = root.GetComponentsInChildren<TMP_Text>(true);
        foreach (TMP_Text text in texts) text.font = _japaneseFont;
    }

    private static GameObject CreatePanel(Transform parent, string name, float x, float y, float width, float height, Color color)
    {
        GameObject go = new GameObject(name, typeof(RectTransform), typeof(Image));
        go.transform.SetParent(parent, false);
        SetRect(go.GetComponent<RectTransform>(), x, y, width, height);
        Image image = go.GetComponent<Image>();
        image.color = color;
        image.raycastTarget = false;
        return go;
    }

    private TMP_Text CreateText(Transform parent, string name, string content, float fontSize, FontStyles style,
        TextAlignmentOptions alignment, Color color, float x, float y, float width, float height)
    {
        GameObject go = new GameObject(name, typeof(RectTransform), typeof(TextMeshProUGUI));
        go.transform.SetParent(parent, false);
        SetRect(go.GetComponent<RectTransform>(), x, y, width, height);
        TextMeshProUGUI text = go.GetComponent<TextMeshProUGUI>();
        text.text = content;
        text.fontSize = fontSize;
        text.fontStyle = style;
        text.alignment = alignment;
        text.color = color;
        text.enableWordWrapping = false;
        text.overflowMode = TextOverflowModes.Ellipsis;
        text.raycastTarget = false;
        if (_japaneseFont != null) text.font = _japaneseFont;
        return text;
    }

    private TMP_Text CreateText(Transform parent, string name, string content, float fontSize, FontStyles style,
        TextAlignmentOptions alignment, Color color, float x, float y, float width, float height, bool raycastTarget)
    {
        TMP_Text text = CreateText(parent, name, content, fontSize, style, alignment, color, x, y, width, height);
        text.raycastTarget = raycastTarget;
        return text;
    }

    private Button CreateButton(Transform parent, string name, string label, float x, float y, float width, float height, Color color, float fontSize)
    {
        GameObject go = new GameObject(name, typeof(RectTransform), typeof(Image), typeof(Button));
        go.transform.SetParent(parent, false);
        SetRect(go.GetComponent<RectTransform>(), x, y, width, height);
        Image image = go.GetComponent<Image>();
        image.color = color;
        image.raycastTarget = true;
        Button button = go.GetComponent<Button>();
        button.targetGraphic = image;
        ColorBlock colors = button.colors;
        colors.highlightedColor = new Color(Mathf.Min(color.r + 0.12f, 1f), Mathf.Min(color.g + 0.12f, 1f), Mathf.Min(color.b + 0.12f, 1f), 1f);
        colors.pressedColor = new Color(color.r * 0.75f, color.g * 0.75f, color.b * 0.75f, 1f);
        button.colors = colors;
        CreateText(go.transform, "Label", label, fontSize, FontStyles.Bold, TextAlignmentOptions.Center, TextMain, 0, 0, width, height, false);
        return button;
    }

    private static void Bind(Button button, UdonBehaviour target, string eventName)
    {
        if (target == null)
        {
            Debug.LogError("Backing UdonBehaviour was not found.");
            return;
        }
        UnityEventTools.AddStringPersistentListener(button.onClick, target.SendCustomEvent, eventName);
        EditorUtility.SetDirty(button);
    }

    private static void SetRect(RectTransform rect, float x, float y, float width, float height)
    {
        rect.anchorMin = new Vector2(0f, 1f);
        rect.anchorMax = new Vector2(0f, 1f);
        rect.pivot = new Vector2(0f, 1f);
        rect.anchoredPosition = new Vector2(x, -y);
        rect.sizeDelta = new Vector2(width, height);
        rect.localScale = Vector3.one;
    }
}
#endif
