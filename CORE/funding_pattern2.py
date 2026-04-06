



class FundingFilter1:
    """
    Инварианты расчета:

    if phm_fundung > 0 and binance_funding > 0:
        val = abs(phm_fundung - binance_funding)
    elif phm_fundung < 0 and binance_funding < 0:
        val = abs(abs(phm_fundun) - abs(binance_funding))
    else:
        val = abs(phm_fundun - binance_funding)   

    вся конструкция эквивалена: val = abs(phm_fundung - binance_funding)
    
    """
