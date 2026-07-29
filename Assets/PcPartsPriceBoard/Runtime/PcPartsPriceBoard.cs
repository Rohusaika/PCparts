using TMPro;
using UdonSharp;
using UnityEngine;
using VRC.SDK3.Data;
using VRC.SDK3.StringLoading;
using VRC.SDKBase;

[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class PcPartsPriceBoard : UdonSharpBehaviour
{
    [Header("Remote JSON")]
    public VRCUrl dataUrl;
    public bool loadOnStart = true;

    [Header("Header")]
    public TMP_Text titleText;
    public TMP_Text updatedText;
    public TMP_Text sourceText;
    public TMP_Text statusText;
    public TMP_Text categoryText;
    public TMP_Text groupText;
    public TMP_Text pageText;

    [Header("Rows (same array length)")]
    public GameObject[] rowObjects;
    public TMP_Text[] nameTexts;
    public TMP_Text[] priceTexts;
    public TMP_Text[] arrowTexts;

    [Header("Display")]
    public int maximumItems = 512;
    public int itemsPerPage = 56;
    public Color priceUpColor = new Color(1f, 0.27f, 0.27f, 1f);
    public Color priceDownColor = new Color(0.25f, 0.64f, 1f, 1f);
    public Color priceSameColor = Color.white;
    public Color unavailableColor = new Color(0.62f, 0.62f, 0.62f, 1f);

    private string[] _category;
    private string[] _group;
    private string[] _name;
    private int[] _price;
    private int[] _previousPrice;
    private int[] _sortScore;
    private bool[] _comparisonAvailable;
    private bool[] _stale;
    private int _itemCount;

    private int[] _filteredIndices;
    private string[] _groups;
    private int _groupCount;
    private int _groupIndex;
    private string _currentCategory = "CPU";
    private int _currentPage;
    private bool _isLoading;

    private void Start()
    {
        AllocateArrays();
        if (titleText != null) titleText.text = "PC PARTS PRICE BOARD";
        SetStatus("価格データを待機中");
        if (loadOnStart) Refresh();
    }

    private void AllocateArrays()
    {
        int capacity = maximumItems;
        if (capacity < 64) capacity = 64;
        if (capacity > 2048) capacity = 2048;

        _category = new string[capacity];
        _group = new string[capacity];
        _name = new string[capacity];
        _price = new int[capacity];
        _previousPrice = new int[capacity];
        _sortScore = new int[capacity];
        _comparisonAvailable = new bool[capacity];
        _stale = new bool[capacity];
        _filteredIndices = new int[capacity];
        _groups = new string[64];
    }

    public void Refresh()
    {
        if (_isLoading) return;
        if (VRCUrl.IsNullOrEmpty(dataUrl))
        {
            SetStatus("JSON URLが未設定です");
            return;
        }

        _isLoading = true;
        SetStatus("価格データを取得中…");
        VRCStringDownloader.LoadUrl(dataUrl, this);
    }

    public override void OnStringLoadSuccess(IVRCStringDownload result)
    {
        _isLoading = false;
        ParseJson(result.Result);
    }

    public override void OnStringLoadError(IVRCStringDownload result)
    {
        _isLoading = false;
        SetStatus("取得失敗: HTTP " + result.ErrorCode + " / " + result.Error);
    }

    private void ParseJson(string json)
    {
        DataToken rootToken;
        if (!VRCJson.TryDeserializeFromJson(json, out rootToken) || rootToken.TokenType != TokenType.DataDictionary)
        {
            SetStatus("JSONの解析に失敗しました: " + rootToken.ToString());
            return;
        }

        DataDictionary root = rootToken.DataDictionary;
        string updatedAt = ReadString(root, "updatedAt", "更新時刻不明");
        string source = ReadString(root, "source", "価格.com");

        DataToken itemsToken;
        if (!root.TryGetValue("items", TokenType.DataList, out itemsToken))
        {
            SetStatus("JSONにitems配列がありません");
            return;
        }

        DataList items = itemsToken.DataList;
        _itemCount = 0;

        int i = 0;
        while (i < items.Count && _itemCount < _category.Length)
        {
            DataToken itemToken = items[i];
            if (itemToken.TokenType == TokenType.DataDictionary)
            {
                DataDictionary item = itemToken.DataDictionary;
                string category = ReadString(item, "category", "");
                string group = ReadString(item, "group", "その他");
                string name = ReadString(item, "name", "名称不明");
                int price = ReadInt(item, "price", 0);
                int previousPrice = ReadInt(item, "previousPrice", price);
                int sortScore = ReadInt(item, "sortScore", 0);
                bool enabled = ReadBool(item, "enabled", true);

                if (enabled && category != "" && name != "")
                {
                    _category[_itemCount] = category;
                    _group[_itemCount] = group;
                    _name[_itemCount] = name;
                    _price[_itemCount] = price;
                    _previousPrice[_itemCount] = previousPrice;
                    _sortScore[_itemCount] = sortScore;
                    _comparisonAvailable[_itemCount] = ReadBool(item, "comparisonAvailable", true);
                    _stale[_itemCount] = ReadBool(item, "stale", false);
                    _itemCount++;
                }
            }
            i++;
        }

        if (updatedText != null) updatedText.text = "更新: " + updatedAt;
        if (sourceText != null) sourceText.text = "参照: " + source;

        _currentPage = 0;
        BuildGroupList();
        Render();
        SetStatus(_itemCount + "件を読み込みました");
    }

    private string ReadString(DataDictionary dictionary, string key, string fallback)
    {
        DataToken token;
        if (dictionary.TryGetValue(key, TokenType.String, out token)) return token.String;
        return fallback;
    }

    private int ReadInt(DataDictionary dictionary, string key, int fallback)
    {
        DataToken token;
        if (dictionary.TryGetValue(key, out token) && token.IsNumber) return (int)token.Double;
        return fallback;
    }

    private bool ReadBool(DataDictionary dictionary, string key, bool fallback)
    {
        DataToken token;
        if (dictionary.TryGetValue(key, TokenType.Boolean, out token)) return token.Boolean;
        return fallback;
    }

    public void TabCPU() { SelectCategory("CPU"); }
    public void TabGPU() { SelectCategory("GPU"); }
    public void TabDDR4() { SelectCategory("DDR4"); }
    public void TabDDR5() { SelectCategory("DDR5"); }
    public void TabSSD() { SelectCategory("SSD"); }
    public void TabHDD() { SelectCategory("HDD"); }

    private void SelectCategory(string category)
    {
        _currentCategory = category;
        _currentPage = 0;
        _groupIndex = 0;
        BuildGroupList();
        Render();
    }

    public void PreviousGroup()
    {
        if (_groupCount <= 1) return;
        _groupIndex--;
        if (_groupIndex < 0) _groupIndex = _groupCount - 1;
        _currentPage = 0;
        Render();
    }

    public void NextGroup()
    {
        if (_groupCount <= 1) return;
        _groupIndex++;
        if (_groupIndex >= _groupCount) _groupIndex = 0;
        _currentPage = 0;
        Render();
    }

    public void PreviousPage()
    {
        if (_currentPage > 0)
        {
            _currentPage--;
            Render();
        }
    }

    public void NextPage()
    {
        int count = BuildFilteredIndexList();
        int pageCount = GetPageCount(count);
        if (_currentPage + 1 < pageCount)
        {
            _currentPage++;
            Render();
        }
    }

    private void BuildGroupList()
    {
        _groupCount = 1;
        _groups[0] = "すべて";

        int i = 0;
        while (i < _itemCount && _groupCount < _groups.Length)
        {
            if (_category[i] == _currentCategory)
            {
                string candidate = _group[i];
                bool exists = false;
                int g = 1;
                while (g < _groupCount)
                {
                    if (_groups[g] == candidate)
                    {
                        exists = true;
                        break;
                    }
                    g++;
                }

                if (!exists)
                {
                    _groups[_groupCount] = candidate;
                    _groupCount++;
                }
            }
            i++;
        }

        if (_groupIndex >= _groupCount) _groupIndex = 0;
    }

    private int BuildFilteredIndexList()
    {
        int count = 0;
        string selectedGroup = _groups[_groupIndex];
        int i = 0;
        while (i < _itemCount)
        {
            bool categoryMatches = _category[i] == _currentCategory;
            bool groupMatches = selectedGroup == "すべて" || _group[i] == selectedGroup;
            if (categoryMatches && groupMatches)
            {
                _filteredIndices[count] = i;
                count++;
            }
            i++;
        }

        // Stable insertion sort: higher performance/sort score appears toward the top.
        i = 1;
        while (i < count)
        {
            int value = _filteredIndices[i];
            int j = i - 1;
            while (j >= 0 && ShouldComeBefore(value, _filteredIndices[j]))
            {
                _filteredIndices[j + 1] = _filteredIndices[j];
                j--;
            }
            _filteredIndices[j + 1] = value;
            i++;
        }

        return count;
    }

    private bool ShouldComeBefore(int leftIndex, int rightIndex)
    {
        if (_sortScore[leftIndex] != _sortScore[rightIndex])
            return _sortScore[leftIndex] > _sortScore[rightIndex];

        if (_price[leftIndex] != _price[rightIndex])
            return _price[leftIndex] > _price[rightIndex];

        // Equal-score entries keep their catalog order for Udon compatibility.
        return false;
    }

    private void Render()
    {
        if (rowObjects == null || nameTexts == null || priceTexts == null || arrowTexts == null) return;

        int slotCount = rowObjects.Length;
        if (nameTexts.Length < slotCount) slotCount = nameTexts.Length;
        if (priceTexts.Length < slotCount) slotCount = priceTexts.Length;
        if (arrowTexts.Length < slotCount) slotCount = arrowTexts.Length;
        if (itemsPerPage > 0 && itemsPerPage < slotCount) slotCount = itemsPerPage;

        int filteredCount = BuildFilteredIndexList();
        int pageCount = GetPageCount(filteredCount);
        if (_currentPage >= pageCount) _currentPage = pageCount - 1;
        if (_currentPage < 0) _currentPage = 0;

        if (categoryText != null) categoryText.text = CategoryLabel(_currentCategory);
        if (groupText != null) groupText.text = "‹  " + _groups[_groupIndex] + "  ›";
        if (pageText != null) pageText.text = (pageCount == 0 ? "0 / 0" : (_currentPage + 1) + " / " + pageCount);

        int slot = 0;
        int start = _currentPage * slotCount;
        while (slot < slotCount)
        {
            int filteredPosition = start + slot;
            bool visible = filteredPosition < filteredCount;
            rowObjects[slot].SetActive(visible);

            if (visible)
            {
                int dataIndex = _filteredIndices[filteredPosition];
                string suffix = _stale[dataIndex] ? " ※" : "";
                nameTexts[slot].text = _name[dataIndex] + suffix;

                int price = _price[dataIndex];
                if (price <= 0)
                {
                    priceTexts[slot].text = "取得なし";
                    arrowTexts[slot].text = "—";
                    arrowTexts[slot].color = unavailableColor;
                    priceTexts[slot].color = unavailableColor;
                }
                else
                {
                    priceTexts[slot].text = FormatYen(price);
                    priceTexts[slot].color = Color.white;
                    SetArrow(slot, dataIndex);
                }
            }
            slot++;
        }
    }

    private void SetArrow(int slot, int dataIndex)
    {
        if (!_comparisonAvailable[dataIndex])
        {
            arrowTexts[slot].text = "→";
            arrowTexts[slot].color = priceSameColor;
            return;
        }

        int current = _price[dataIndex];
        int previous = _previousPrice[dataIndex];
        if (current > previous)
        {
            arrowTexts[slot].text = "↑";
            arrowTexts[slot].color = priceUpColor;
        }
        else if (current < previous)
        {
            arrowTexts[slot].text = "↓";
            arrowTexts[slot].color = priceDownColor;
        }
        else
        {
            arrowTexts[slot].text = "→";
            arrowTexts[slot].color = priceSameColor;
        }
    }

    private int GetPageCount(int itemCount)
    {
        int pageSize = itemsPerPage;
        if (rowObjects != null && rowObjects.Length < pageSize) pageSize = rowObjects.Length;
        if (pageSize <= 0) return 0;
        if (itemCount <= 0) return 0;
        return (itemCount + pageSize - 1) / pageSize;
    }

    private string FormatYen(int value)
    {
        string digits = value.ToString();
        string formatted = "";
        int fromRight = 0;
        int i = digits.Length - 1;
        while (i >= 0)
        {
            if (fromRight > 0 && fromRight % 3 == 0) formatted = "," + formatted;
            formatted = digits.Substring(i, 1) + formatted;
            fromRight++;
            i--;
        }
        return formatted + "円";
    }

    private string CategoryLabel(string category)
    {
        if (category == "CPU") return "CPU";
        if (category == "GPU") return "GPU";
        if (category == "DDR4") return "DDR4 MEMORY";
        if (category == "DDR5") return "DDR5 MEMORY";
        if (category == "SSD") return "SSD";
        if (category == "HDD") return "HDD (3.5-inch SATA)";
        return category;
    }

    private void SetStatus(string message)
    {
        if (statusText != null) statusText.text = message;
    }
}
